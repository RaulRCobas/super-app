"""
Scraper de super.facua.org. Cubre Mercadona, Carrefour, Dia, Alcampo, Eroski (Hipercor
se ignora, no está en nuestro alcance). FACUA solo vigila un puñado de categorías básicas
por cadena (aceite, leche, huevos, etc.) -- no es un catálogo completo, es un vigilante
de cesta básica. Ver aviso en backend/README.md.

Estructura del sitio (agosto 2026, puede cambiar -- revisa si esto deja de encontrar nada):
  /{cadena}/                      -> categorías de nivel 1 (enlaces con texto "Ver")
  /{cadena}/{categoria}/          -> subcategorías ("Ver") y/o productos ("Histórico")
  cada tile de producto tiene: <img alt="precios NOMBRE en CADENA">, texto
  "Precio hoy: X,XX€", y un enlace de texto "Histórico" -> página de histórico del producto.
"""
import re
import logging
from datetime import date
from bs4 import BeautifulSoup

from common.http import make_session, polite_get
from common.db import get_conn, get_supermarket_id, get_or_create_category, upsert_product_source, insert_price
from normalization.unit_parser import parse_package_size, compute_unit_price

log = logging.getLogger(__name__)

BASE = "https://super.facua.org"
CHAINS = ["mercadona", "carrefour", "dia", "alcampo", "eroski"]  # Hipercor excluido a propósito

PRICE_RE = re.compile(r"Precio hoy:\s*([\d.,]+)\s*€", re.IGNORECASE)
ALT_RE = re.compile(r"^precios\s+(.*?)\s+en\s+\w+$", re.IGNORECASE)


def _get_soup(session, url):
    resp = polite_get(session, url)
    return BeautifulSoup(resp.text, "html.parser")


def _extract_products(soup):
    """Devuelve [{external_id, raw_name, price}] a partir de los tiles 'Histórico' de la página actual."""
    products = []
    for a in soup.find_all("a", string=lambda t: t and t.strip() == "Histórico"):
        href = a.get("href", "")
        external_id = href.rstrip("/").split("/")[-1]
        container = a
        name, price = None, None
        for _ in range(4):  # sube hasta 4 niveles buscando el contenedor del tile
            container = container.parent
            if container is None:
                break
            if name is None:
                img = container.find("img", alt=True)
                if img:
                    m = ALT_RE.match(img["alt"].strip())
                    if m:
                        name = m.group(1).strip()
            if price is None:
                m = PRICE_RE.search(container.get_text(" ", strip=True))
                if m:
                    price = float(m.group(1).replace(".", "").replace(",", ".")) if "." in m.group(1) and "," in m.group(1) else float(m.group(1).replace(",", "."))
            if name and price is not None:
                break
        if href and name and price is not None:
            products.append({"external_id": external_id, "raw_name": name, "price": price})
    return products


def _extract_subcategory_links(soup, base_url):
    links = []
    for a in soup.find_all("a", string=lambda t: t and t.strip() == "Ver"):
        href = a.get("href", "")
        if href.startswith("/"):
            href = BASE + href
        if href.startswith(base_url) and href != base_url:
            links.append(href)
    return links


def scrape_chain(session, conn, slug: str, today: str):
    supermarket_id = get_supermarket_id(conn, slug)
    root_url = f"{BASE}/{slug}/"
    to_visit = [(root_url, None, None)]  # (url, category_name, parent_category_id)
    visited = set()
    total_products = 0

    while to_visit:
        url, cat_name, parent_cat_id = to_visit.pop()
        if url in visited:
            continue
        visited.add(url)
        soup = _get_soup(session, url)

        cat_id = parent_cat_id
        if cat_name:
            cat_id = get_or_create_category(conn, cat_name, source="facua", parent_id=parent_cat_id)

        for sub_url in _extract_subcategory_links(soup, url):
            sub_name = sub_url.rstrip("/").split("/")[-1].replace("-", " ")
            to_visit.append((sub_url, sub_name, cat_id))

        for p in _extract_products(soup):
            unit_type, unit_size = parse_package_size(p["raw_name"])
            unit_price = compute_unit_price(p["price"], unit_type, unit_size)
            ps_id = upsert_product_source(
                conn, supermarket_id, external_id=f"{slug}:{p['external_id']}",
                raw_name=p["raw_name"], raw_category=cat_name,
                package_size_raw=p["raw_name"],
            )
            insert_price(conn, ps_id, price=p["price"], captured_at=today,
                          source="facua", unit_price=unit_price)
            total_products += 1

    log.info("FACUA %s: %d precios capturados", slug, total_products)
    return total_products


def run(chains=None):
    chains = chains or CHAINS
    session = make_session()
    today = date.today().isoformat()
    with get_conn() as conn:
        for slug in chains:
            try:
                scrape_chain(session, conn, slug, today)
            except Exception:
                log.exception("Fallo scrapeando FACUA/%s -- se continúa con el resto", slug)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
