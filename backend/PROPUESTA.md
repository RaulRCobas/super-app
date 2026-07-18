# Backend comparador de precios — propuesta (v0, sin código aún)

## 1. Esquema de base de datos

Motor: propongo **SQLite** para el MVP (cero infraestructura, un fichero, fácil de mover) con posibilidad de migrar a Postgres cuando haya que consultar desde la web en producción con concurrencia. Confírmalo abajo.

```
supermarket
  id            INTEGER PK
  slug          TEXT UNIQUE   -- 'mercadona','carrefour','lidl','dia','gadis','eroski','supeco','alcampo'
  name          TEXT

zone                                  -- almacén/código postal por cadena
  id                INTEGER PK
  supermarket_id    FK supermarket
  postal_code       TEXT
  warehouse_code    TEXT NULL         -- p.ej. 'wh' de Mercadona
  label             TEXT NULL

category
  id            INTEGER PK
  parent_id     FK category NULL     -- subcategoría -> categoría
  name          TEXT
  source        TEXT                 -- de qué fuente vino la taxonomía (mercadona/facua/manual)

product                               -- catálogo CANÓNICO, ya normalizado
  id            INTEGER PK
  canonical_name TEXT
  category_id   FK category
  brand         TEXT NULL
  barcode       TEXT NULL UNIQUE
  unit_type     TEXT                 -- 'kg' | 'l' | 'unidad'
  unit_size     NUMERIC NULL         -- p.ej. 1, 0.5, 12 (uds)
  created_at    DATETIME

product_source                        -- fila CRUDA tal y como llega de cada cadena, pre-match
  id            INTEGER PK
  product_id    FK product NULL       -- NULL hasta que el matcher lo resuelve
  supermarket_id FK supermarket
  external_id   TEXT                  -- id/slug en la web de origen
  raw_name      TEXT
  raw_category  TEXT NULL
  raw_subcategory TEXT NULL
  package_size_raw TEXT NULL          -- '750 g', '6x330ml', etc. (texto tal cual)
  barcode       TEXT NULL
  first_seen_at DATETIME
  last_seen_at  DATETIME

price                                 -- histórico, INSERT-only, nunca UPDATE
  id            INTEGER PK
  product_source_id FK product_source
  zone_id       FK zone
  price         NUMERIC               -- precio absoluto en €
  unit_price    NUMERIC NULL          -- €/kg, €/l o €/ud, calculado
  captured_at   DATE
  source        TEXT                  -- 'facua' | 'mercadona_api' | 'scraper_lidl' | ...

product_match_log                     -- auditoría del matcher (para poder revisar/corregir a mano)
  id            INTEGER PK
  product_source_id FK product_source
  product_id    FK product
  method        TEXT                  -- 'barcode' | 'fuzzy' | 'manual'
  confidence    NUMERIC
  matched_at    DATETIME
```

Por qué así:
- `product_source` guarda SIEMPRE el dato crudo de cada cadena (nombre, categoría propia de esa web) separado del `product` canónico — así nunca perdemos el dato original y podemos re-matchear si mejoramos el algoritmo.
- `price` es histórico apend-only por `zone_id` + fecha: nunca se sobreescribe, se consulta "el precio vigente" como el `MAX(captured_at)` por producto+zona.
- El total/comparación de la lista se calcula en consulta (SQL), no se guarda materializado.

## 2. Normalización entre cadenas

Dos señales, en este orden de prioridad:

1. **Código de barras (EAN)** cuando esté disponible (via Open Food Facts o si la propia cadena lo expone) → match exacto, confianza 1.0. Esto es lo único realmente fiable entre cadenas.
2. **Fuzzy matching de texto** cuando no hay barcode (caso más común, sobre todo en marca blanca — cada cadena la llama distinto): normalizar (minúsculas, sin acentos, sin marca de la cadena tipo "Hacendado"/"Carrefour Selección"), extraer marca + formato con regex (`(\d+[.,]?\d*)\s*(g|kg|ml|l|ud|uds)`), y comparar con `rapidfuzz` (token_sort_ratio) DENTRO de la misma categoría/subcategoría — nunca comparar productos de categorías distintas aunque el texto sea parecido.
3. Umbral de confianza configurable (p.ej. ≥0.85 auto-match, 0.6–0.85 a revisión manual en `product_match_log`, <0.6 se queda sin matchear en `product_source`).

**Formato del envase**: todo precio se normaliza a `unit_price` (€/kg, €/l o €/ud) usando `unit_size` extraído del `package_size_raw`. La comparación "más barato" siempre se hace por `unit_price`, no por precio absoluto — así un paquete de 500g más caro pero más barato por kilo gana correctamente.

## 3. Plan de módulos (ingesta)

```
ingestion/
  facua_client.py        # MVP — cubre Mercadona, Carrefour, Dia, Alcampo, Eroski (Hipercor se ignora, no está en el alcance)
  mercadona_catalog.py   # catálogo + categorías vía API no oficial — ver aviso legal abajo
scrapers/
  lidl.py                # Playwright (web con JS)
  supeco.py               # Playwright
  gadis.py                # Playwright o requests+BS4 si el HTML es estático
normalization/
  matcher.py             # barcode + fuzzy, categoría-acotado
  unit_parser.py          # regex de formato/tamaño -> unit_price
api/
  compare.py             # dada una lista de productos + código postal -> más barato por item + total por cadena
common/
  http.py                # sesión con headers realistas, reintentos+backoff, rate limiting
  db.py                  # conexión/esquema
scheduler/
  run_daily.py           # orquesta el orden: facua -> mercadona -> scrapers -> matcher
```

`api/compare.py` (consulta, no HTTP todavía — decidimos formato de exposición abajo):
```
compare_list(product_ids: list[int], postal_code: str) -> {
  "por_item": [{product_id, cheapest_supermarket, unit_price, price}, ...],
  "por_cadena": [{supermarket, total, items_encontrados, items_sin_precio}, ...]
}
```

## 4. Aviso legal — léelo antes de que sigamos

- El `robots.txt` de Mercadona **bloquea `/api` para crawlers**. Usar ese endpoint de forma automatizada no respeta esa directiva, aunque sea un proyecto personal/familiar y de bajo volumen. Es una práctica común en proyectos hobby (hay varios en GitHub) pero el riesgo/responsabilidad es tuyo, no mío. Alternativas:
  - (a) Usar igualmente la API de Mercadona pero con volumen mínimo (1 vez al día, tu código postal únicamente, nunca todo el catálogo completo) — asumes el riesgo.
  - (b) Prescindir de la API de Mercadona y cubrir Mercadona solo vía FACUA (que sí lo agrega públicamente) — más lento a actualizarse pero sin tocar el endpoint bloqueado.
- Lidl/Supeco/Gadis no tienen robots.txt público que bloquee explícitamente scraping en las rutas de producto que necesitamos, pero scrapear sigue estando sujeto a sus términos de servicio; lo trataremos igual con bajo volumen, headers realistas, y cache agresivo (no volver a pedir lo que ya tenemos de hoy).
- Todo el código llevará un aviso en cabecera: uso personal/no comercial, respetar rate limits, no redistribuir los datos.

## 5. Decisiones que necesito que confirmes

Ver formulario adjunto.
