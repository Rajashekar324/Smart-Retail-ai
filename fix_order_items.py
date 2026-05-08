import sqlite3
from pathlib import Path

DB_PATH = Path("data/store.db")

if not DB_PATH.exists():
    raise SystemExit(f"Database file not found: {DB_PATH}")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Load products by price for matching
products = cur.execute("SELECT id, name, price, sizes FROM products").fetchall()
price_to_product = {float(price): (prod_id, name, sizes) for prod_id, name, price, sizes in products}

orders = cur.execute(
    "SELECT id, order_number, customer_name, total_amount FROM orders"
).fetchall()

missing_orders = []
for order_id, order_number, customer_name, total_amount in orders:
    item_count = cur.execute(
        "SELECT COUNT(*) FROM order_items WHERE order_id = ?", (order_id,)
    ).fetchone()[0]
    if item_count == 0:
        missing_orders.append((order_id, order_number, customer_name, total_amount))

print(f"Found {len(orders)} orders, {len(missing_orders)} with no order items.")

inserted = 0
for order_id, order_number, customer_name, total_amount in missing_orders:
    matched = False
    for qty in (4, 3, 2, 1):
        if qty == 0:
            continue
        candidate_price = total_amount / qty
        if abs(candidate_price - round(candidate_price, 2)) > 1e-6:
            continue
        candidate_price = round(candidate_price, 2)
        if candidate_price in price_to_product:
            prod_id, prod_name, sizes = price_to_product[candidate_price]
            size = sizes.split(",")[0] if sizes else "Standard"
            cur.execute(
                "INSERT INTO order_items (order_id, product_id, product_name, size, quantity, unit_price) VALUES (?, ?, ?, ?, ?, ?)",
                (order_id, prod_id, prod_name, size, qty, candidate_price),
            )
            print(
                f"Inserted order item for order {order_number} -> {prod_name} x{qty} @ {candidate_price}"
            )
            inserted += 1
            matched = True
            break
    if not matched:
        print(
            f"WARNING: Could not infer product for order {order_number} (total {total_amount})"
        )

conn.commit()
conn.close()
print(f"Done. Inserted {inserted} missing order item records.")
