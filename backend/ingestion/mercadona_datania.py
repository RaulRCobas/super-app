"""
Carga el catálogo de Mercadona desde el dataset público `datania/mercadona-catalog`
(Hugging Face) -- NO llamamos a tienda.mercadona.es/api directamente, porque su
robots.txt lo bloquea para crawlers. datania ya hace esa descarga por su cuenta y
publica el resultado limpio.

Requiere: pip install datasets huggingface_hub
También admite un export manual tuyo como alternativa/relleno (ver load_manual_export).

⚠️ El nombre real de las columnas puede variar según cuándo se generó el dataset --
este loader inspecciona las columnas disponibles y usa la primera que reconoce para
cada campo. Si algún campo sale siempre a None, imprime `dataset.column_names` y
ajusta COLUMN_CANDIDATES abajo.
"""
import json
import logging
from datetime import date

from common.db import get_conn, get_supermarket_id, get_or_create_category, upsert_product_source, insert_price
from normalization.unit_parser import parse_package_size, compute_unit_price

log = logging.getLogger(__name__)

HF_DATASET = "datania/mercadona-catalog"

COLUMN_CANDIDATES = {
    "external_id": ["id", "product_id", "external_id"],
    "name": ["display_name", "name", "product_name"],
    "category": ["category_name", "category", "section"],
    "package": ["package_size", "size", "format", "unit_size"],
    "price": ["price", "unit_price", "current_price", "price_instructions"],
    "barcode": ["ean", "barcode"],
}


def _first_present(row: dict, keys: list[str]):
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return None


def _load_rows_from_hf():
    from datasets import load_dataset
    ds = load_dataset(HF_DATASET, split="train")
    log.info("Columnas del dataset: %s", ds.column_names)
    return ds


def load_manual_export(path: str):
    """Alternativa: un JSON/CSV que tú exportes a mano con al menos name+price (+category, barcode si tienes)."""
    with open(path, encoding="utf-8") as f:
        if path.endswith(".json"):
            return json.load(f)
        import csv
        return list(csv.DictReader(f))


def ingest(rows, today: str):
    with get_conn() as conn:
        supermarket_id = get_supermarket_id(conn, "mercadona")
        count = 0
        for row in rows:
            row = dict(row)
            name = _first_present(row, COLUMN_CANDIDATES["name"])
            price = _first_present(row, COLUMN_CANDIDATES["price"])
            if not name or price is None:
                continue
            external_id = str(_first_present(row, COLUMN_CANDIDATES["external_id"]) or name)
            category = _first_present(row, COLUMN_CANDIDATES["category"])
            package = _first_present(row, COLUMN_CANDIDATES["package"])
            barcode = _first_present(row, COLUMN_CANDIDATES["barcode"])
            cat_id = get_or_create_category(conn, category, source="mercadona") if category else None

            unit_type, unit_size = parse_package_size(str(package) if package else name)
            unit_price = compute_unit_price(float(price), unit_type, unit_size)

            ps_id = upsert_product_source(
                conn, supermarket_id, external_id=f"mercadona:{external_id}",
                raw_name=str(name), raw_category=str(category) if category else None,
                package_size_raw=str(package) if package else None,
                barcode=str(barcode) if barcode else None,
            )
            insert_price(conn, ps_id, price=float(price), captured_at=today,
                         source="mercadona_datania", unit_price=unit_price)
            count += 1
        log.info("Mercadona (datania): %d productos ingeridos", count)
        return count


def run(manual_export_path: str | None = None):
    today = date.today().isoformat()
    if manual_export_path:
        rows = load_manual_export(manual_export_path)
    else:
        rows = _load_rows_from_hf()
    ingest(rows, today)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
