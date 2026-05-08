#!/usr/bin/env python3
"""Test script to verify total revenue calculation"""

from app.database import SessionLocal
from app.models import Order
from sqlalchemy import func

def test_total_revenue():
    db = SessionLocal()
    try:
        # Calculate total revenue from all completed/paid orders
        total_revenue = db.query(Order).filter(Order.payment_status.in_(["Paid", "Completed"])).with_entities(func.sum(Order.total_amount)).scalar() or 0

        print(f"Total Revenue: ₹{total_revenue:.2f}")

        # Show breakdown by payment status
        paid_orders = db.query(Order).filter(Order.payment_status == "Paid").all()
        completed_orders = db.query(Order).filter(Order.payment_status == "Completed").all()

        paid_total = sum(order.total_amount for order in paid_orders)
        completed_total = sum(order.total_amount for order in completed_orders)

        print(f"Paid orders total: ₹{paid_total:.2f}")
        print(f"Completed orders total: ₹{completed_total:.2f}")
        print(f"Total orders: {len(paid_orders) + len(completed_orders)}")

    finally:
        db.close()

if __name__ == "__main__":
    test_total_revenue()