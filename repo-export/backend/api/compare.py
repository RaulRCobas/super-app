"""
Dada una lista de productos (canónicos, ya emparejados) y opcionalmente una zona,
devuelve el supermercado más barato por item y el total por cadena.
Compara siempre por unit_price (€/kg, €/l, €/ud) cuando existe; si no, por precio absoluto.
"""
from common.db import get_conn


def _latest_prices_for_product(conn, product_id: int, zone_id: int | None = None):
    """Último precio conocido por supermercado para un product_id."""
    query = """
        SELECT s.slug AS supermarket, p.price, p.unit_price, p.captured_at
        FROM price p
        JOIN product_source ps ON ps.id = p.product_source_id
        JOIN supermarket s ON s.id = ps.supermarket_id
        WHERE ps.product_id = ?
    """
    params = [product_id]
    if zone_id is not None:
        query += " AND (p.zone_id = ? OR p.zone_id IS NULL)"
        params.append(zone_id)
    query += " AND p.captured_at = (SELECT MAX(p2.captured_at) FROM price p2 WHERE p2.product_source_id = p.product_source_id)"
    return conn.execute(query, params).fetchall()


def compare_list(product_ids: list[int], zone_id: int | None = None):
    per_item = []
    totals = {}
    missing_by_chain = {}

    with get_conn() as conn:
        for pid in product_ids:
            rows = _latest_prices_for_product(conn, pid, zone_id)
            if not rows:
                per_item.append({"product_id": pid, "cheapest_supermarket": None, "price": None, "unit_price": None})
                continue
            best = min(rows, key=lambda r: r["unit_price"] if r["unit_price"] is not None else r["price"])
            per_item.append({
                "product_id": pid,
                "cheapest_supermarket": best["supermarket"],
                "price": best["price"],
                "unit_price": best["unit_price"],
            })
            seen_chains = set()
            for r in rows:
                chain = r["supermarket"]
                seen_chains.add(chain)
                totals.setdefault(chain, {"total": 0.0, "items_encontrados": 0, "items_sin_precio": 0})
                totals[chain]["total"] += r["price"]
                totals[chain]["items_encontrados"] += 1

    por_cadena = [
        {"supermarket": chain, **vals} for chain, vals in sorted(totals.items(), key=lambda kv: kv[1]["total"])
    ]
    return {"por_item": per_item, "por_cadena": por_cadena}
