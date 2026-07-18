"""Crea backend/data/precios.db a partir de schema.sql. Idempotente (CREATE TABLE IF NOT EXISTS)."""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "precios.db"
SCHEMA_PATH = ROOT / "db" / "schema.sql"

SUPERMARKETS = [
    ("mercadona", "Mercadona"), ("carrefour", "Carrefour"), ("lidl", "Lidl"),
    ("dia", "Dia"), ("gadis", "Gadis"), ("eroski", "Eroski"),
    ("supeco", "Supeco"), ("alcampo", "Alcampo"),
]

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    for slug, name in SUPERMARKETS:
        conn.execute(
            "INSERT OR IGNORE INTO supermarket (slug, name) VALUES (?, ?)", (slug, name)
        )
    conn.commit()
    conn.close()
    print(f"BBDD lista en {DB_PATH}")

if __name__ == "__main__":
    init_db()
