"""Ejecuta solo Lidl/Supeco/Gadis (necesitan configuración manual, ver comentarios en cada uno) + emparejado + export."""
import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.init_db import init_db
from scrapers import lidl, supeco, gadis
from normalization import run_matching
from export import build_static_json

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

def main():
    log.info("1/4 -- asegurando esquema de BBDD")
    init_db()
    log.info("2/4 -- Lidl / Supeco / Gadis")
    for name, mod in [("Lidl", lidl), ("Supeco", supeco), ("Gadis", gadis)]:
        try:
            mod.run()
        except Exception:
            log.exception("%s: fallo o no configurado todavía -- se continúa", name)
    log.info("3/4 -- emparejando product_source -> product canónico")
    run_matching.run()
    log.info("4/4 -- exportando JSON estático para la web")
    build_static_json.build()
    log.info("Lidl/Supeco/Gadis: pipeline completo.")

if __name__ == "__main__":
    main()
