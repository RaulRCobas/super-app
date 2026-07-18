import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "precios.db"

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def get_supermarket_id(conn, slug: str) -> int:
    row = conn.execute("SELECT id FROM supermarket WHERE slug = ?", (slug,)).fetchone()
    if not row:
        raise ValueError(f"Supermercado desconocido: {slug}")
    return row["id"]

def get_or_create_category(conn, name: str, source: str, parent_id: int | None = None) -> int:
    row = conn.execute(
        "SELECT id FROM category WHERE name = ? AND source = ? AND (parent_id IS ? )",
        (name, source, parent_id),
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO category (parent_id, name, source) VALUES (?, ?, ?)",
        (parent_id, name, source),
    )
    return cur.lastrowid

def get_or_create_zone(conn, supermarket_id: int, postal_code: str) -> int:
    row = conn.execute(
        "SELECT id FROM zone WHERE supermarket_id = ? AND postal_code = ?",
        (supermarket_id, postal_code),
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO zone (supermarket_id, postal_code) VALUES (?, ?)",
        (supermarket_id, postal_code),
    )
    return cur.lastrowid

def upsert_product_source(conn, supermarket_id: int, external_id: str, raw_name: str,
                           raw_category: str | None = None, raw_subcategory: str | None = None,
                           package_size_raw: str | None = None, barcode: str | None = None) -> int:
    row = conn.execute(
        "SELECT id FROM product_source WHERE supermarket_id = ? AND external_id = ?",
        (supermarket_id, external_id),
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE product_source SET raw_name=?, raw_category=?, raw_subcategory=?, "
            "package_size_raw=?, barcode=?, last_seen_at=datetime('now') WHERE id=?",
            (raw_name, raw_category, raw_subcategory, package_size_raw, barcode, row["id"]),
        )
        return row["id"]
    cur = conn.execute(
        "INSERT INTO product_source (supermarket_id, external_id, raw_name, raw_category, "
        "raw_subcategory, package_size_raw, barcode) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (supermarket_id, external_id, raw_name, raw_category, raw_subcategory, package_size_raw, barcode),
    )
    return cur.lastrowid

def insert_price(conn, product_source_id: int, price: float, captured_at: str, source: str,
                  zone_id: int | None = None, unit_price: float | None = None):
    conn.execute(
        "INSERT INTO price (product_source_id, zone_id, price, unit_price, captured_at, source) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (product_source_id, zone_id, price, unit_price, captured_at, source),
    )
