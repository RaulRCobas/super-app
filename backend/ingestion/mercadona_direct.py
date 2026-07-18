"""
Cliente directo de la API no oficial de Mercadona (tienda.mercadona.es/api), en vez del
dataset de terceros (que resultó estar roto e inestable). Más simple: reutiliza
common/http.py (reintentos, backoff, límite de peticiones) igual que el resto del backend.

⚠️ Aviso de uso responsable: el robots.txt de Mercadona bloquea /api para crawlers.
Esto se ejecuta asumiendo ese riesgo (ver explicación en el chat / backend/README.md):
volumen bajo, 1 vez al día, un único código postal, con pausas entre peticiones.
No lo uses con más frecuencia ni concurrencia de la necesaria.
"""
import logging
from datetime import date

from common.http import make_session, polite_get
from common.db import get_conn, get_supermarket_id, get_or_create_category, get_or_create_zone, upsert_product_source, insert_price
from normalization.unit_parser import parse_package_size, compute_unit_price

log = logging.getLogger(__name__)

API_BASE = "https://tienda.mercadona.es/api"
POSTAL_CODE = "15011"  # mismo código postal que el resto del backend -- nunca mezclar zonas


def set_postal_code(session, postal_code=POSTAL_CODE):
    resp = session.put(f"{API_BASE}/postal-codes/actions/change-pc/", json={"new_postal_code": postal_code}, timeout=20)
    resp.raise_for_status()


def _first(d, keys, default=None):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _extract_price(product):
    pi = product.get("price_instructions") or {}
    price = _first(pi, ["unit_price", "bulk_price", "reference_price"])
    if price is None:
        price = product.get("price")
    try:
        return float(price) if price is not None else None
    except (TypeError, ValueError):
        return None


def _extract_package(product):
    pi = product.get("price_instructions") or {}
    return _first(pi, ["unit_size", "size_format", "reference_format"]) or product.get("packaging") or product.get("display_name", "")


def fetch_categories(session):
    resp = polite_get(session, f"{API_BASE}/categories/")
    return resp.json().get("results", [])


def fetch_category_detail(session, cat_id):
    resp = polite_get(session, f"{API_BASE}/categories/{cat_id}/")
    return resp.json()


def _iter_leaf_categories(cats, parent_name=None):
    """Las categorías de nivel 1 traen 'categories' anidadas; las hojas ya no tienen subcategorías."""
    for c in cats:
        name = c.get("name") or c.get("display_name")
        subs = c.get("categories")
        if subs:
            yield from _iter_leaf_categories(subs, name)
        else:
            yield c, parent_name


def run():
    session = make_session()
    set_postal_code(session)
    today = date.today().isoformat()

    with get_conn() as conn:
        supermarket_id = get_supermarket_id(conn, "mercadona")
        zone_id = get_or_create_zone(conn, supermarket_id, POSTAL_CODE)
        top_categories = fetch_categories(session)

        total = 0
        for leaf, parent_name in _iter_leaf_categories(top_categories):
            cat_id = leaf.get("id")
            cat_name = leaf.get("name") or leaf.get("display_name") or "Sin categoría"
            if not cat_id:
                continue
            try:
                detail = fetch_category_detail(session, cat_id)
            except Exception:
                log.exception("Mercadona: fallo leyendo categoría %s (%s) -- se continúa", cat_id, cat_name)
                continue

            products = detail.get("products") or []
            if not products:
                for sub in (detail.get("categories") or []):
                    products += sub.get("products") or []

            for p in products:
                price = _extract_price(p)
                name = p.get("display_name") or p.get("name")
                if price is None or not name:
                    continue
                package = _extract_package(p)
                unit_type, unit_size = parse_package_size(str(package))
                unit_price = compute_unit_price(price, unit_type, unit_size)
                ps_id = upsert_product_source(
                    conn, supermarket_id, external_id=f"mercadona:{p.get('id')}",
                    raw_name=name, raw_category=cat_name,
                    package_size_raw=str(package), barcode=p.get("ean") or p.get("barcode"),
                )
                insert_price(conn, ps_id, price=price, captured_at=today, source="mercadona_api",
                             zone_id=zone_id, unit_price=unit_price)
                total += 1
        log.info("Mercadona (API directa): %d productos capturados", total)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
