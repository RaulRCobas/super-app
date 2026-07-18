"""Orquesta el pipeline diario. Pensado para ejecutarse 1 vez/día (cron, GitHub Actions, etc.)."""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db.init_db import init_db
from ingestion import facua_client, mercadona_direct
from scrapers import lidl, supeco, gadis
from normalization import run_matching
from export import build_static_json

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main():
    log.info("1/5 -- asegurando esquema de BBDD")
    init_db()

    log.info("2/5 -- catálogo Mercadona (API directa)")
    try:
        mercadona_direct.run()
    except Exception:
        log.exception("Fallo cargando catálogo de Mercadona -- se continúa")

    log.info("3/5 -- precios FACUA (Mercadona, Carrefour, Dia, Alcampo, Eroski)")
    facua_client.run()

    log.info("3b/5 -- Lidl / Supeco / Gadis (necesitan configuración manual, ver comentarios en cada fichero)")
    for name, mod in [("Lidl", lidl), ("Supeco", supeco), ("Gadis", gadis)]:
        try:
            mod.run()
        except Exception:
            log.exception("%s: fallo o no configurado todavía -- se continúa", name)

    log.info("4/5 -- emparejando product_source -> product canónico (sin esto el JSON sale vacío)")
    run_matching.run()

    log.info("5/5 -- exportando JSON estático para la web")
    build_static_json.build()

    log.info("Pipeline diario completo.")


if __name__ == "__main__":
    main()
