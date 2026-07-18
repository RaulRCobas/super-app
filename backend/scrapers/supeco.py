"""
Supeco (www.supeco.es) es una web puramente informativa: localizador de tiendas y
folleto (leaflet) semanal en PDF. NO tiene tienda online ni catálogo de productos con
precio consultable página a página -- lo hemos comprobado directamente. No hay "PLP" que
scrapear con requests+BeautifulSoup ni con Playwright: no existe.

La única fuente de precios de Supeco es su folleto semanal, servido como visor flipbook
por tienda en la URL https://www.supeco.es/folletos/?id=<ID_TIENDA> -- el id se asigna
por JS así que no se puede derivar solo de la home; hay que entrar manualmente, elegir la
tienda de A Coruña en "Consulta nuestro folleto" y leer el número en la URL resultante.
Alternativa más simple si el visor da problemas: https://www.tiendeo.com/Catalogos/142422
(catálogo de Supeco ya extraído por un tercero, en HTML normal en vez de flipbook).

Parsear precios de un PDF/visor de folleto es intrínsecamente frágil (el diseño cambia
cada semana, los precios están dentro de imágenes/maquetación libre, no en una tabla) --
esto es un best-effort, no una fuente fiable para comparación automática. Revisa siempre
los resultados a mano antes de fiarte de ellos.

Requiere: pip install pdfplumber requests
"""
import re
import logging
from datetime import date

from common.http import make_session, polite_get
from common.db import get_conn, get_supermarket_id, upsert_product_source, insert_price
from normalization.unit_parser import parse_package_size, compute_unit_price

log = logging.getLogger(__name__)

FOLLETO_URL = "https://www.supeco.es/folletos/?id=70"  # tienda A Coruña, confirmado por el usuario
# precio con símbolo €, tipo "1,99 €" o "1.99€", cerca de una línea de texto (nombre de producto)
PRICE_LINE_RE = re.compile(r"^(.*?)\s+(\d{1,3}[.,]\d{2})\s*€", re.MULTILINE)


def find_current_folleto_pdf_url(playwright_page) -> str | None:
    """
    Intenta localizar un PDF real detrás del visor flipbook navegando con Playwright
    (bloqueado desde este entorno para inspeccionarlo en vivo, así que esto es best-effort):
    busca cualquier enlace/atributo que apunte a un .pdf en la página o en sus iframes.
    Si no lo encuentra, no hay PDF descargable y hay que caer en manual_pdf_path.
    """
    playwright_page.goto(FOLLETO_URL, wait_until="domcontentloaded", timeout=45000)
    playwright_page.wait_for_timeout(4000)
    candidates = playwright_page.eval_on_selector_all(
        "a[href], iframe[src], [data-pdf-url], [data-src]",
        "els => els.map(e => e.getAttribute('href') || e.getAttribute('src') || e.getAttribute('data-pdf-url') || e.getAttribute('data-src')).filter(Boolean)",
    )
    for c in candidates:
        if c and ".pdf" in c.lower():
            return c if c.startswith("http") else ("https://www.supeco.es" + c)
    return None


def scrape_folleto_pdf(pdf_bytes: bytes):
    import io
    import pdfplumber
    products = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for m in PRICE_LINE_RE.finditer(text):
                name = m.group(1).strip(" -–\t")
                price_raw = m.group(2).replace(".", "").replace(",", ".")
                if len(name) < 3:
                    continue
                try:
                    price = float(price_raw)
                except ValueError:
                    continue
                products.append({"raw_name": name, "price": price})
    return products


def run(manual_pdf_path: str | None = None):
    """
    Sin `manual_pdf_path`, intenta localizar un PDF real detrás del visor (id=70, tienda
    A Coruña) con Playwright -- probablemente falle si el visor no expone ningún .pdf
    (algunos flipbooks solo pintan imágenes por canvas, sin PDF descargable en absoluto).
    Si le pasas la ruta a un PDF que hayas descargado tú mismo, lo parsea igualmente --
    opción más fiable hoy por hoy mientras no se confirme cómo expone el PDF el visor.
    """
    today = date.today().isoformat()
    session = make_session()

    if manual_pdf_path:
        with open(manual_pdf_path, "rb") as f:
            pdf_bytes = f.read()
    else:
        from playwright.sync_api import sync_playwright
        pdf_url = None
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ))
            try:
                pdf_url = find_current_folleto_pdf_url(page)
            except Exception:
                log.exception("Supeco: fallo navegando al visor del folleto")
            browser.close()
        if not pdf_url:
            log.warning(
                "Supeco: no se ha localizado un PDF descargable detrás del visor (%s). "
                "Es probable que el flipbook pinte imágenes por canvas/JS sin PDF real. "
                "Descárgalo tú a mano (o haz una captura) y llama a run(manual_pdf_path=...).",
                FOLLETO_URL,
            )
            return
        pdf_bytes = polite_get(session, pdf_url).content

    products = scrape_folleto_pdf(pdf_bytes)
    if not products:
        log.warning("Supeco: el parseo del PDF no encontró productos -- revisa el formato del folleto actual.")
        return

    with get_conn() as conn:
        supermarket_id = get_supermarket_id(conn, "supeco")
        for i, p in enumerate(products):
            unit_type, unit_size = parse_package_size(p["raw_name"])
            unit_price = compute_unit_price(p["price"], unit_type, unit_size)
            ps_id = upsert_product_source(
                conn, supermarket_id, external_id=f"supeco:folleto:{today}:{i}",
                raw_name=p["raw_name"], package_size_raw=p["raw_name"],
            )
            insert_price(conn, ps_id, price=p["price"], captured_at=today,
                         source="scraper_supeco_folleto", unit_price=unit_price)
        log.info("Supeco: %d líneas de folleto ingeridas (revisar a mano, es un parseo frágil)", len(products))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
