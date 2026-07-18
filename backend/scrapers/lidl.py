"""
Lidl no está en FACUA. Su tienda online en España (lidl.es/es/onlineshop) es una SPA
que carga el catálogo por JS -- necesita Playwright, no basta requests+BeautifulSoup.

⚠️ Aviso importante: el "onlineshop" de Lidl España es históricamente un catálogo de NO
alimentación (electrónica, hogar, bricolaje, ropa...) -- Lidl normalmente NO vende
alimentación/frescos online en España, solo en tienda física. Antes de invertir tiempo
aquí, confirma si lo que ves en tu lista de la compra (comida) tiene siquiera equivalente
en ese catálogo -- si no, este scraper solo te servirá para categorías de no-alimentación.

Requiere: pip install playwright && playwright install chromium
Los selectores de abajo son un punto de partida razonable para una PLP (product listing
page) típica -- pero no se han podido verificar contra el HTML real desde este entorno.
Ejecuta con --headed la primera vez e inspecciona/ajusta CATEGORY_URLS y los selectores.
"""
import logging
from datetime import date

from common.db import get_conn, get_supermarket_id, get_or_create_category, upsert_product_source, insert_price
from normalization.unit_parser import parse_package_size, compute_unit_price

log = logging.getLogger(__name__)

BASE = "https://www.lidl.es"
# TODO: rellena con las categorías reales que te interesen tras inspeccionar /es/onlineshop
CATEGORY_URLS = [
    # ("nombre categoria", "https://www.lidl.es/es/onlineshop/c/alguna-categoria/a12345"),
]

PRODUCT_CARD_SELECTOR = "div[data-grid-item], .plpp-product-card, article.product-grid-box"
NAME_SELECTOR = ".plpp-product-card__title, .odsc-tile__title, h3"
PRICE_SELECTOR = ".plpp-price__price, .odsc-price__value, [data-price]"


def scrape_category(page, url: str):
    page.goto(url, wait_until="networkidle", timeout=30000)
    page.wait_for_selector(PRODUCT_CARD_SELECTOR, timeout=15000)
    cards = page.query_selector_all(PRODUCT_CARD_SELECTOR)
    results = []
    for card in cards:
        name_el = card.query_selector(NAME_SELECTOR)
        price_el = card.query_selector(PRICE_SELECTOR)
        if not name_el or not price_el:
            continue
        name = name_el.inner_text().strip()
        price_text = price_el.inner_text().strip()
        price = _parse_price(price_text)
        if price is None:
            continue
        href = card.query_selector("a")
        external_id = (href.get_attribute("href") or name).rstrip("/").split("/")[-1] if href else name
        results.append({"external_id": external_id, "raw_name": name, "price": price})
    return results


def _parse_price(text: str):
    import re
    m = re.search(r"([\d.,]+)", text)
    if not m:
        return None
    raw = m.group(1)
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def run():
    if not CATEGORY_URLS:
        log.warning("Lidl: CATEGORY_URLS está vacío -- añade las categorías reales antes de ejecutar. Ver comentarios en este fichero.")
        return
    from playwright.sync_api import sync_playwright

    today = date.today().isoformat()
    with get_conn() as conn, sync_playwright() as p:
        supermarket_id = get_supermarket_id(conn, "lidl")
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ))
        total = 0
        for cat_name, url in CATEGORY_URLS:
            try:
                cat_id = get_or_create_category(conn, cat_name, source="lidl")
                for prod in scrape_category(page, url):
                    unit_type, unit_size = parse_package_size(prod["raw_name"])
                    unit_price = compute_unit_price(prod["price"], unit_type, unit_size)
                    ps_id = upsert_product_source(
                        conn, supermarket_id, external_id=f"lidl:{prod['external_id']}",
                        raw_name=prod["raw_name"], raw_category=cat_name,
                        package_size_raw=prod["raw_name"],
                    )
                    insert_price(conn, ps_id, price=prod["price"], captured_at=today,
                                 source="scraper_lidl", unit_price=unit_price)
                    total += 1
            except Exception:
                log.exception("Fallo en categoría Lidl '%s' -- se continúa", cat_name)
            page.wait_for_timeout(1500)  # pausa entre categorías
        browser.close()
        log.info("Lidl: %d precios capturados", total)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
