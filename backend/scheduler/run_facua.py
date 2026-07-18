"""Ejecuta solo FACUA (Mercadona, Carrefour, Dia, Alcampo, Eroski) + emparejado + export."""
import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.init_db import init_db
from ingestion import facua_client
from normalization import run_matching
from export import build_static_json

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

def main():
    log.info("1/4 -- asegurando esquema de BBDD")
    init_db()
    log.info("2/4 -- precios FACUA (Mercadona, Carrefour, Dia, Alcampo, Eroski)")
    facua_client.run()
    log.info("3/4 -- emparejando product_source -> product canónico")
    run_matching.run()
    log.info("4/4 -- exportando JSON estático para la web")
    build_static_json.build()
    log.info("FACUA: pipeline completo.")

if __name__ == "__main__":
    main()
