"""
Pieza que faltaba para que la comparación funcione de verdad: hasta ahora facua_client.py
y mercadona_datania.py solo rellenaban `product_source` (fila cruda por cadena), pero
NUNCA se creaba ni enlazaba el `product` canónico -- build_static_json.py hace JOIN contra
`product`, así que sin esto el JSON exportado siempre salía vacío. Esto es lo que faltaba
para "activar" la página de verdad.

Estrategia (pensada para maximizar cobertura en un proyecto personal, no para precisión
perfecta -- documentado, no oculto):
  1. Barcode exacto si existe -> match seguro.
  2. Fuzzy dentro de la misma etiqueta de categoría (texto normalizado) contra productos
     canónicos ya existentes -> si score >= AUTO_ACCEPT, se enlaza.
  3. Si no hay candidato razonable, se crea un `product` canónico NUEVO a partir de esa
     fila -- así el producto no se pierde y queda listo para que futuras filas de OTRAS
     cadenas se emparejen con él. Esto es lo que va ampliando cobertura cadena a cadena.
Se registra todo en product_match_log para poder auditar/corregir a mano más adelante.
"""
import logging

from common.db import get_conn, get_or_create_category
from normalization.matcher import find_best_match, match_by_barcode, normalize_text

log = logging.getLogger(__name__)

# más permisivo que el umbral por defecto del matcher (85): aquí preferimos fusionar
# productos parecidos entre cadenas antes que duplicar canónicos -- ajusta si ves falsos positivos.
AUTO_ACCEPT = 75


def _category_key(text):
    return normalize_text(text or "")


def _category_name(conn, category_id):
    if category_id is None:
        return None
    row = conn.execute("SELECT name FROM category WHERE id = ?", (category_id,)).fetchone()
    return row["name"] if row else None


def run():
    with get_conn() as conn:
        unmatched = conn.execute(
            "SELECT id, raw_name, raw_category, barcode FROM product_source WHERE product_id IS NULL"
        ).fetchall()
        log.info("%d filas de product_source sin emparejar", len(unmatched))

        all_products_cache = None
        created, matched_barcode, matched_fuzzy = 0, 0, 0

        for ps in unmatched:
            product_id, method, confidence = None, None, None

            if ps["barcode"]:
                product_id = match_by_barcode(conn, ps["barcode"])
                if product_id:
                    method, confidence = "barcode", 100

            if not product_id:
                if all_products_cache is None:
                    all_products_cache = [dict(r) for r in conn.execute(
                        "SELECT id AS product_id, canonical_name, category_id FROM product"
                    ).fetchall()]
                key = _category_key(ps["raw_category"])
                if key:
                    candidates = [c for c in all_products_cache if _category_key(_category_name(conn, c["category_id"])) == key]
                else:
                    candidates = all_products_cache
                best_id, score, m = find_best_match(ps["raw_name"], None, candidates)
                if best_id and score >= AUTO_ACCEPT:
                    product_id, method, confidence = best_id, "fuzzy", score

            if not product_id:
                cat_id = get_or_create_category(conn, ps["raw_category"], source="unified") if ps["raw_category"] else None
                cur = conn.execute(
                    "INSERT INTO product (canonical_name, category_id, barcode) VALUES (?, ?, ?)",
                    (ps["raw_name"], cat_id, ps["barcode"]),
                )
                product_id, method, confidence = cur.lastrowid, "new_canonical", None
                created += 1
                if all_products_cache is not None:
                    all_products_cache.append({"product_id": product_id, "canonical_name": ps["raw_name"], "category_id": cat_id})
            elif method == "barcode":
                matched_barcode += 1
            else:
                matched_fuzzy += 1

            conn.execute("UPDATE product_source SET product_id = ? WHERE id = ?", (product_id, ps["id"]))
            conn.execute(
                "INSERT INTO product_match_log (product_source_id, product_id, method, confidence) VALUES (?, ?, ?, ?)",
                (ps["id"], product_id, method, confidence),
            )

        log.info(
            "Emparejamiento completo: %d canónicos nuevos, %d por barcode, %d por fuzzy",
            created, matched_barcode, matched_fuzzy,
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
