"""
Supeco (www.supeco.es) es una web puramente informativa: localizador de tiendas y
folleto (leaflet) semanal en PDF. NO tiene tienda online ni catálogo de productos con
precio consultable página a página -- lo hemos comprobado directamente. No hay "PLP" que
scrapear con requests+BeautifulSoup ni con Playwright: no existe.

La única fuente de precios de Supeco es su folleto PDF semanal (enlace "CONSULTA NUESTRO
FOLLETO" en la home). Parsear precios de un PDF de folleto es intrínsecamente frágil (el
diseño cambia cada semana, los precios están dentro de imágenes/maquetación libre, no en
una tabla) -- esto es un best-effort, no una fuente fiable para comparación automática.
Revisa siempre los resultados a mano antes de fiarte de ellos.

Requiere: pip install pdfplumber requests
"""
import re
import logging
from datetime import date

from common.http import make_session, polite_get
from common.db import get_conn, get_supermarket_id, upsert_product_source, insert_price
from normalization.unit_parser import parse_package_size, compute_unit_price

log = logging.getLogger(__name__)

FOLLETO_PAGE = "https://www.supeco.es/"
# precio con símbolo €, tipo "1,99 €" o "1.99€", cerca de una línea de texto (nombre de producto)
PRICE_LINE_RE = re.compile(r"^(.*?)\s+(\d{1,3}[.,]\d{2})\s*€", re.MULTILINE)


def find_current_folleto_pdf_url(session) -> str | None:
    """
    TODO: la home no expone el PDF con un href directo y estable (lleva a un visor).
    Inspecciona manualmente 'CONSULTA NUESTRO FOLLETO' en supeco.es y localiza la URL real
    del PDF (o del visor -- si es un visor tipo flipbook, esto no funcionará y hará falta
    Playwright para capturar el PDF que carga por JS, o descargarlo desde el propio visor).
    """
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
    Sin `manual_pdf_path`, intenta localizar el folleto solo (probablemente falle, ver
    find_current_folleto_pdf_url). Si le pasas la ruta a un PDF que hayas descargado tú
    mismo del folleto de Supeco, lo parsea igualmente -- opción más fiable hoy por hoy.
    """
    today = date.today().isoformat()
    session = make_session()

    if manual_pdf_path:
        with open(manual_pdf_path, "rb") as f:
            pdf_bytes = f.read()
    else:
        pdf_url = find_current_folleto_pdf_url(session)
        if not pdf_url:
            log.warning(
                "Supeco: no se ha localizado el PDF del folleto automáticamente. "
                "Descárgalo tú desde supeco.es y llama a run(manual_pdf_path=...)."
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
