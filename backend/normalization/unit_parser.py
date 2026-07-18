"""
Extrae precios de tamaño/paquete: '750 g', '1,5 L', '6x330ml', '12 uds' -> (unit_type, unit_size).
unit_size se expresa siempre en la unidad base: kg, l o ud (nunca en g/ml).
"""
import re

_NUM = r"(\d+(?:[.,]\d+)?)"

# paquetes múltiples: "6x330ml", "4 x 1.5l"
MULTI_RE = re.compile(rf"{_NUM}\s*[xX]\s*{_NUM}\s*(kg|g|l|ml|ud|uds|und|unidades)", re.IGNORECASE)
SIMPLE_RE = re.compile(rf"{_NUM}\s*(kg|g|l|ml|ud|uds|und|unidades)", re.IGNORECASE)

_TO_BASE = {"kg": ("kg", 1), "g": ("kg", 0.001), "l": ("l", 1), "ml": ("l", 0.001),
            "ud": ("unidad", 1), "uds": ("unidad", 1), "und": ("unidad", 1), "unidades": ("unidad", 1)}

def _num(s: str) -> float:
    return float(s.replace(",", "."))

def parse_package_size(text: str):
    """Devuelve (unit_type, unit_size) o (None, None) si no se reconoce el formato."""
    if not text:
        return None, None
    m = MULTI_RE.search(text)
    if m:
        count = _num(m.group(1))
        size = _num(m.group(2))
        unit_raw = m.group(3).lower()
        base_unit, factor = _TO_BASE[unit_raw]
        return base_unit, round(count * size * factor, 4)
    m = SIMPLE_RE.search(text)
    if m:
        size = _num(m.group(1))
        unit_raw = m.group(2).lower()
        base_unit, factor = _TO_BASE[unit_raw]
        return base_unit, round(size * factor, 4)
    return None, None

def compute_unit_price(price: float, unit_type: str | None, unit_size: float | None):
    """€/kg, €/l o €/ud. None si no se pudo determinar el formato (nunca dividir a ciegas)."""
    if not unit_type or not unit_size or unit_size <= 0:
        return None
    return round(price / unit_size, 4)
