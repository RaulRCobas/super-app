"""
Genera public_data/precios.json -- el JSON estático que subes junto al resto de la web.
La app web (Lista de Compra.dc.html) puede hacer fetch('./precios.json') una vez lo
alojes en el mismo dominio.
"""
import json
import logging
from datetime import date
from pathlib import Path

from common.db import get_conn

log = logging.getLogger(__name__)
OUT_PATH = Path(__file__).resolve().parent.parent / "public_data" / "precios.json"


def build():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT pr.canonical_name, pr.id AS product_id, cat.name AS category_name,
                   s.slug AS supermarket, p.price, p.unit_price, p.captured_at
            FROM price p
            JOIN product_source ps ON ps.id = p.product_source_id
            JOIN supermarket s ON s.id = ps.supermarket_id
            JOIN product pr ON pr.id = ps.product_id
            LEFT JOIN category cat ON cat.id = pr.category_id
            WHERE p.captured_at = (
                SELECT MAX(p2.captured_at) FROM price p2 WHERE p2.product_source_id = p.product_source_id
            )
        """).fetchall()

    by_product = {}
    for r in rows:
        entry = by_product.setdefault(r["product_id"], {
            "product_id": r["product_id"], "name": r["canonical_name"],
            "category": r["category_name"], "prices": [],
        })
        entry["prices"].append({
            "supermarket": r["supermarket"], "price": r["price"],
            "unit_price": r["unit_price"], "captured_at": r["captured_at"],
        })

    payload = {
        "generated_at": date.today().isoformat(),
        "products": list(by_product.values()),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Escrito %s (%d productos)", OUT_PATH, len(by_product))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    build()
