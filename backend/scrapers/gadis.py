"""
Gadis. La web informativa gadisytu.com/gadis.es NO es la tienda -- la compra online real
está en https://www.gadisline.com/, y esa tienda requiere cuenta de cliente para navegar
el catálogo con precios (típico de los supermercados españoles con reparto a domicilio).

Eso cambia el aviso legal: aquí no hablamos de "scrapear una web pública anónima", sino de
automatizar tu PROPIA sesión ya logueada en tu cuenta de Gadisline. Sigue sin estar exento
de sus términos de servicio, pero el marco es distinto (es tu cuenta, tus datos de acceso).
Antes de activar esto en producción, confírmalo tú mismo entrando a gadisline.com.

Requiere: pip install playwright && playwright install chromium
Necesitas credenciales propias de Gadisline -- pásalas por variables de entorno, nunca las
escribas en este fichero: GADISLINE_EMAIL / GADISLINE_PASSWORD.

Los selectores de abajo son un punto de partida razonable (no verificado desde este
entorno, gadisline.com bloqueó el acceso directo). Ejecuta con headless=False la primera
vez para ajustar selectores contra el HTML real.
"""
import os
import logging
from datetime import date

from common.db import get_conn, get_supermarket_id, get_or_create_category, get_or_create_zone, upsert_product_source, insert_price
from normalization.unit_parser import parse_package_size, compute_unit_price

log = logging.getLogger(__name__)

BASE = "https://www.gadisline.com"
LOGIN_URL = f"{BASE}/es/login"
POSTAL_CODE = "15011"  # fija siempre la zona antes de leer precios -- nunca compares precios de códigos postales distintos
# TODO: rellena con las categorías reales tras loguearte e inspeccionar el menú
CATEGORY_URLS = [
    # ("nombre categoria", "https://www.gadisline.com/es/categoria/alguna-categoria"),
]

PRODUCT_CARD_SELECTOR = ".product-item, .product-card, article.product"
NAME_SELECTOR = ".product-item__name, .product-name, h3"
PRICE_SELECTOR = ".product-item__price, .price, [data-price]"
# TODO: ajusta este selector tras inspeccionar el flujo real de "cambiar tienda/código postal"
# de Gadisline una vez logueado (suele ser un modal o un campo en la cabecera).
POSTAL_CODE_INPUT_SELECTOR = "input[name=postalCode], input[placeholder*='código postal' i]"
POSTAL_CODE_SUBMIT_SELECTOR = "button[type=submit], button:has-text('Confirmar')"


def _parse_price(text: str):
    import re
    m = re.search(r"([\d.,]+)", text)
    if not m:
        return None
    raw = m.group(1)
    raw = raw.replace(".", "").replace(",", ".") if "," in raw and "." in raw else raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def login(page):
    email = os.environ.get("GADISLINE_EMAIL")
    password = os.environ.get("GADISLINE_PASSWORD")
    if not email or not password:
        raise RuntimeError("Define GADISLINE_EMAIL y GADISLINE_PASSWORD como variables de entorno.")
    page.goto(LOGIN_URL, wait_until="networkidle", timeout=30000)
    page.fill("input[type=email], input[name=email]", email)
    page.fill("input[type=password], input[name=password]", password)
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")


def set_postal_code(page, postal_code: str = POSTAL_CODE):
    """
    Fija la zona/tienda de Gadisline al código postal dado -- imprescindible antes de leer
    ningún precio, porque Gadisline sirve precios distintos por tienda/zona igual que el
    resto de cadenas. Ajusta los selectores en POSTAL_CODE_INPUT_SELECTOR/_SUBMIT_SELECTOR
    tras comprobar el flujo real (probablemente un modal "elige tu tienda" tras loguear).
    """
    try:
        page.wait_for_selector(POSTAL_CODE_INPUT_SELECTOR, timeout=8000)
        page.fill(POSTAL_CODE_INPUT_SELECTOR, postal_code)
        page.click(POSTAL_CODE_SUBMIT_SELECTOR)
        page.wait_for_load_state("networkidle")
    except Exception:
        log.warning(
            "Gadis: no se ha podido fijar el código postal %s automáticamente -- "
            "ajusta POSTAL_CODE_INPUT_SELECTOR/POSTAL_CODE_SUBMIT_SELECTOR tras inspeccionar "
            "el flujo real en gadisline.com.", postal_code,
        )


def scrape_category(page, url: str):
    page.goto(url, wait_until="networkidle", timeout=30000)
    page.wait_for_selector(PRODUCT_CARD_SELECTOR, timeout=15000)
    results = []
    for card in page.query_selector_all(PRODUCT_CARD_SELECTOR):
        name_el = card.query_selector(NAME_SELECTOR)
        price_el = card.query_selector(PRICE_SELECTOR)
        if not name_el or not price_el:
            continue
        price = _parse_price(price_el.inner_text())
        if price is None:
            continue
        name = name_el.inner_text().strip()
        href = card.query_selector("a")
        external_id = (href.get_attribute("href") or name).rstrip("/").split("/")[-1] if href else name
        results.append({"external_id": external_id, "raw_name": name, "price": price})
    return results


def run():
    if not CATEGORY_URLS:
        log.warning("Gadis: CATEGORY_URLS vacío -- ver comentarios en este fichero.")
        return
    from playwright.sync_api import sync_playwright

    today = date.today().isoformat()
    with get_conn() as conn, sync_playwright() as p:
        supermarket_id = get_supermarket_id(conn, "gadis")
        zone_id = get_or_create_zone(conn, supermarket_id, POSTAL_CODE)
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        login(page)
        set_postal_code(page)
        total = 0
        for cat_name, url in CATEGORY_URLS:
            try:
                get_or_create_category(conn, cat_name, source="gadis")
                for prod in scrape_category(page, url):
                    unit_type, unit_size = parse_package_size(prod["raw_name"])
                    unit_price = compute_unit_price(prod["price"], unit_type, unit_size)
                    ps_id = upsert_product_source(
                        conn, supermarket_id, external_id=f"gadis:{prod['external_id']}",
                        raw_name=prod["raw_name"], raw_category=cat_name,
                        package_size_raw=prod["raw_name"],
                    )
                    insert_price(conn, ps_id, price=prod["price"], captured_at=today,
                                 source="scraper_gadis", zone_id=zone_id, unit_price=unit_price)
                    total += 1
            except Exception:
                log.exception("Fallo en categoría Gadis '%s' -- se continúa", cat_name)
            page.wait_for_timeout(1500)
        browser.close()
        log.info("Gadis: %d precios capturados", total)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
