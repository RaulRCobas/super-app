"""
Lidl no está en FACUA. Su tienda online en España (lidl.es) es una SPA (Vue) que carga
el catálogo por JS -- necesita Playwright, no basta requests+BeautifulSoup.

✓ Confirmado por navegación real: lidl.es sí vende alimentación online (fruta y verdura,
carne, lácteos, panadería, despensa, congelados, bebidas) -- las categorías y selectores
de abajo están verificados contra el HTML real, no son una suposición.

Requiere: pip install playwright && playwright install chromium
Notas del HTML real:
- El precio numérico también está en el atributo JSON data-gridbox-impression del
  contenedor de la tarjeta (campo "price") -- más fiable que parsear el texto "1.99€"
  si algún día el texto cambia de formato.
- El id de producto aparece en li[id='grid-item-0-<ID>'].
"""
import logging
from datetime import date

from common.db import get_conn, get_supermarket_id, get_or_create_category, upsert_product_source, insert_price
from normalization.unit_parser import parse_package_size, compute_unit_price

log = logging.getLogger(__name__)

BASE = "https://www.lidl.es"
CATEGORY_URLS = [
    ("Fruta y verdura", "https://www.lidl.es/h/fruta-y-verdura/h10071012"),
    ("Carne y charcutería", "https://www.lidl.es/h/carne-y-charcuteria/h10095752"),
    ("Lácteos, Queso y Huevos", "https://www.lidl.es/h/lacteos-queso-y-huevos/h10095761"),
    ("Panadería y Bollería", "https://www.lidl.es/h/panaderia-y-bolleria/h10096086"),
    ("Despensa", "https://www.lidl.es/h/despensa/h10096095"),
    ("Congelados", "https://www.lidl.es/h/congelados/h10071049"),
    ("Bebidas", "https://www.lidl.es/h/bebidas/h10071022"),
]

PRODUCT_CARD_SELECTOR = "li[id^='grid-item-'] .product-grid-box"
NAME_SELECTOR = ".product-grid-box__title[data-qa-label='product-grid-box-title']"
PRICE_SELECTOR = ".product-grid-box__price .ods-price__value"


def _dismiss_cookie_banner(page):
    for sel in ["#onetrust-accept-btn-handler", "button:has-text('Aceptar todas')", "button:has-text('Aceptar')"]:
        try:
            page.click(sel, timeout=3000)
            return True
        except Exception:
            continue
    return False


def scrape_category(page, url: str):
    page.goto(url, wait_until="networkidle", timeout=30000)
    _dismiss_cookie_banner(page)
    try:
        page.wait_for_selector(PRODUCT_CARD_SELECTOR, timeout=8000)
    except Exception:
        pass
    # el grid carga por scroll infinito -- baja varias veces para forzar que pinte más tarjetas
    for _ in range(6):
        page.mouse.wheel(0, 2500)
        page.wait_for_timeout(500)
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
