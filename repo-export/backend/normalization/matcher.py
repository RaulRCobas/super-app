"""
Empareja product_source (fila cruda por cadena) con product (canónico), para poder
comparar el mismo producto entre supermercados. Nunca compara categorías distintas.

Requiere `pip install rapidfuzz`.
"""
import re
import unicodedata
from rapidfuzz import fuzz

FUZZY_AUTO_THRESHOLD = 85     # >= esto: match automático
FUZZY_REVIEW_THRESHOLD = 60   # entre este y el auto: a product_match_log para revisión manual

# marcas propias de cada cadena que no aportan nada a la comparación (se limpian antes de comparar)
STORE_BRANDS = ["hacendado", "carrefour selección", "carrefour", "dia", "eroski", "auchan",
                "alcampo", "producto alcampo", "el corte inglés", "el corte ingles"]

def normalize_text(s: str) -> str:
    s = s.lower().strip()
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    for brand in STORE_BRANDS:
        s = s.replace(brand, "")
    s = re.sub(r"\d+([.,]\d+)?\s*(kg|g|l|ml|ud|uds|und|unidades)\b", "", s)  # quita formato/tamaño
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def find_best_match(raw_name: str, category_id, candidates: list[dict]):
    """
    candidates: [{"product_id":.., "canonical_name":.., "category_id":..}] ya acotados
    a la MISMA categoría que raw_name (acotar categoría es responsabilidad del caller).
    Devuelve (product_id, confidence, method) o (None, 0, None).
    """
    target = normalize_text(raw_name)
    best_id, best_score = None, 0
    for c in candidates:
        score = fuzz.token_sort_ratio(target, normalize_text(c["canonical_name"]))
        if score > best_score:
            best_id, best_score = c["product_id"], score
    if best_score >= FUZZY_AUTO_THRESHOLD:
        return best_id, best_score, "fuzzy"
    if best_score >= FUZZY_REVIEW_THRESHOLD:
        return best_id, best_score, "fuzzy_review"
    return None, best_score, None

def match_by_barcode(conn, barcode: str):
    if not barcode:
        return None
    row = conn.execute("SELECT id FROM product WHERE barcode = ?", (barcode,)).fetchone()
    return row["id"] if row else None
