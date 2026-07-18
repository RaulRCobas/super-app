-- Esquema SQLite del comparador de precios. Ver backend/README.md para el porqué de cada tabla.

CREATE TABLE IF NOT EXISTS supermarket (
  id            INTEGER PRIMARY KEY,
  slug          TEXT UNIQUE NOT NULL,   -- 'mercadona','carrefour','lidl','dia','gadis','eroski','supeco','alcampo'
  name          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS zone (
  id                INTEGER PRIMARY KEY,
  supermarket_id    INTEGER NOT NULL REFERENCES supermarket(id),
  postal_code       TEXT,
  warehouse_code    TEXT,             -- p.ej. 'wh' de Mercadona, si aplica
  label             TEXT,
  UNIQUE(supermarket_id, postal_code)
);

CREATE TABLE IF NOT EXISTS category (
  id            INTEGER PRIMARY KEY,
  parent_id     INTEGER REFERENCES category(id),
  name          TEXT NOT NULL,
  source        TEXT NOT NULL          -- 'mercadona' | 'facua' | 'manual'
);

CREATE TABLE IF NOT EXISTS product (
  id              INTEGER PRIMARY KEY,
  canonical_name  TEXT NOT NULL,
  category_id     INTEGER REFERENCES category(id),
  brand           TEXT,
  barcode         TEXT UNIQUE,
  unit_type       TEXT NOT NULL DEFAULT 'unidad',  -- 'kg' | 'l' | 'unidad'
  unit_size       NUMERIC,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS product_source (
  id                INTEGER PRIMARY KEY,
  product_id        INTEGER REFERENCES product(id),   -- NULL hasta que el matcher lo resuelve
  supermarket_id    INTEGER NOT NULL REFERENCES supermarket(id),
  external_id       TEXT,                              -- slug/id en la web de origen
  raw_name          TEXT NOT NULL,
  raw_category      TEXT,
  raw_subcategory   TEXT,
  package_size_raw  TEXT,
  barcode           TEXT,
  first_seen_at     TEXT NOT NULL DEFAULT (datetime('now')),
  last_seen_at      TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(supermarket_id, external_id)
);

CREATE TABLE IF NOT EXISTS price (
  id                  INTEGER PRIMARY KEY,
  product_source_id   INTEGER NOT NULL REFERENCES product_source(id),
  zone_id             INTEGER REFERENCES zone(id),
  price               NUMERIC NOT NULL,
  unit_price          NUMERIC,
  captured_at         TEXT NOT NULL,      -- fecha (YYYY-MM-DD)
  source              TEXT NOT NULL       -- 'facua' | 'mercadona_datania' | 'scraper_lidl' | ...
);
CREATE INDEX IF NOT EXISTS idx_price_source_date ON price(product_source_id, captured_at);

CREATE TABLE IF NOT EXISTS product_match_log (
  id                  INTEGER PRIMARY KEY,
  product_source_id   INTEGER NOT NULL REFERENCES product_source(id),
  product_id          INTEGER NOT NULL REFERENCES product(id),
  method              TEXT NOT NULL,      -- 'barcode' | 'fuzzy' | 'manual'
  confidence          NUMERIC,
  matched_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
