# Backend — comparador de precios (MVP)

## Aviso de uso responsable
Este código es para uso personal/familiar, sin fines comerciales. No redistribuyas los datos en bruto de FACUA ni de Mercadona. Respeta los límites de peticiones (`common/http.py` ya aplica pausas y reintentos con backoff) y no aumentes la frecuencia de ejecución por debajo de lo necesario.

## Decisiones de arquitectura tomadas
- **Base de datos**: SQLite (`backend/data/precios.db`), fichero único, sin servidor.
- **Catálogo de Mercadona**: se lee del dataset público `datania/mercadona-catalog` en Hugging Face (ya publicado, actualizado periódicamente por ese proyecto). **No** llamamos nosotros a `tienda.mercadona.es/api`, precisamente porque su `robots.txt` lo bloquea para crawlers.
- **Precios comparados (Mercadona, Carrefour, Dia, Alcampo, Eroski)**: scraping de `super.facua.org` con `requests` + `BeautifulSoup` (el HTML es estático, no hace falta Playwright).
  - ⚠️ **Importante**: FACUA solo vigila un puñado de categorías básicas por cadena (aceite de oliva, aceite de girasol, huevos, leche, y similares), no el catálogo completo. Solo esos productos tendrán comparación de precio real en el MVP.
- **Lidl / Supeco / Gadis**: implementados, con avisos importantes por cadena (léelos antes de activarlos en producción):
  - **Lidl** (`scrapers/lidl.py`): su tienda online es una SPA (Playwright). ⚠️ Ese "onlineshop" es históricamente un catálogo de NO alimentación en España — confirma que cubre lo que compras antes de invertir tiempo ajustando selectores.
  - **Supeco** (`scrapers/supeco.py`): comprobado directamente — **no tiene tienda online ni catálogo con precios**, solo localizador de tiendas y folleto PDF semanal. El scraper parsea ese PDF como mejor esfuerzo (frágil, revisar a mano).
  - **Gadis** (`scrapers/gadis.py`): la tienda real es `gadisline.com`, que exige cuenta de cliente logueada para ver precios. Aquí ya no es "scrapear una web pública", es automatizar tu propia sesión — necesita tus credenciales por variables de entorno (`GADISLINE_EMAIL`/`GADISLINE_PASSWORD`).
  - Los tres necesitan que ajustes los selectores CSS (`CATEGORY_URLS`, etc.) tras inspeccionar el HTML real — no se han podido verificar contra las webs en vivo desde este entorno.
- **Frecuencia**: pensado para ejecutarse una vez al día (`scheduler/run_daily.py`).
- **Exposición hacia la web**: `export/build_static_json.py` genera un `public_data/precios.json` estático que subes junto al resto de la web (no hay servidor/API en vivo en este MVP).

## Instalar
```
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python db/init_db.py                 # crea el esquema
python scheduler/run_daily.py        # ingesta completa + normaliza + exporta JSON
```

## Estructura
```
backend/
  db/schema.sql            esquema SQLite
  db/init_db.py            crea precios.db a partir del esquema
  common/http.py           sesión HTTP con reintentos, backoff, headers realistas
  common/db.py             helpers de conexión
  ingestion/facua_client.py       scraper de super.facua.org (5 cadenas)
  ingestion/mercadona_datania.py  carga el catálogo desde el dataset de Hugging Face
  normalization/unit_parser.py    extrae tamaño/formato -> precio por kg/l/ud
  normalization/matcher.py        empareja product_source -> product canónico
  scrapers/lidl.py, supeco.py, gadis.py   (stubs, fase 2)
  api/compare.py            dada una lista de productos + código postal -> más barato por item y total por cadena
  export/build_static_json.py     genera el JSON estático para la web
  scheduler/run_daily.py    orquesta todo el pipeline diario
```

## Automatizar con GitHub Actions
Ya está listo en `.github/workflows/scrape.yml`:
- Corre cada día a las 05:00 UTC (ajustable) + botón manual "Run workflow" en la pestaña Actions.
- Instala dependencias y Chromium de Playwright, ejecuta `scheduler/run_daily.py`, y commitea de vuelta `backend/public_data/precios.json` y `backend/data/precios.db` (así el histórico de precios persiste entre ejecuciones).
- Si usas el scraper de Gadis, añade `GADISLINE_EMAIL` y `GADISLINE_PASSWORD` como **Secrets** del repo (Settings → Secrets and variables → Actions) — nunca los escribas en el código.
- Como tu web es estática, sirve `backend/public_data/precios.json` desde el mismo dominio que `Lista de Compra.dc.html` (o copia ese fichero a la carpeta de tu web en un paso extra del workflow si viven en repos/carpetas distintas).


1. **Ejecutar el pipeline en algún sitio.** Este backend es Python — no corre solo. Necesitas una máquina (tu portátil, un Raspberry Pi, o un cron de GitHub Actions) donde ejecutar `pip install -r requirements.txt` y luego `python scheduler/run_daily.py` una vez al día.
2. **Subir `public_data/precios.json`** a la misma carpeta que `Lista de Compra.dc.html` en tu dominio — la app hace `fetch('./precios.json')` y en cuanto ese fichero exista con datos, la pestaña Súper se activa sola (ya no hace falta tocar el HTML).
3. **Lidl / Supeco / Gadis** siguen necesitando que ajustes los selectores/credenciales descritos en cada fichero de `scrapers/` contra las webs reales — sin eso solo tendrás Mercadona/Carrefour/Dia/Alcampo/Eroski (vía FACUA) + catálogo Mercadona (vía datania).
4. Ya estaba resuelto en esta vuelta: **faltaba `normalization/run_matching.py`** — antes de esto, `product_source` se rellenaba pero nunca se creaba ni enlazaba el `product` canónico, así que el JSON exportado siempre salía vacío por mucho que corrieras el scraping. Ahora el pipeline lo hace automáticamente en el paso 4/5.

## Cómo amplía cobertura `run_matching.py`
Cada producto nuevo que llega de una cadena intenta emparejarse (barcode exacto, o fuzzy dentro de la misma categoría) contra los canónicos que ya existen; si no encaja con nada, se crea como canónico nuevo en vez de descartarse. Así, cuantas más cadenas ingieras, más productos van fusionándose bajo el mismo `product` y más cobertura de comparación tendrás — no hace falta tocar nada a mano para que esto crezca, solo ejecutar más fuentes.
