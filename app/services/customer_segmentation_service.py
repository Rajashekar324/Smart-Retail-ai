from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import Order, OrderItem, Product, User


class CustomerSegmentationService:
    """Customer segmentation using clustering models"""
    
    def __init__(self):
        pass
    
    def get_customer_features(self, user_id: int, db: Session) -> Dict[str, float]:
        """Extract features for a customer for segmentation"""
        orders = db.query(Order).filter(Order.user_id == user_id).all()
        
        if not orders:
            return self._get_default_features()
        
        # Feature extraction
        total_orders = len(orders)
        total_spent = sum(order.total_amount for order in orders)
        avg_order_value = total_spent / total_orders if total_orders > 0 else 0
        
        # Frequency: orders per month
        first_order = min(orders, key=lambda o: o.created_at)
        months_active = max(1, (datetime.utcnow() - first_order.created_at).days / 30)
        order_frequency = total_orders / months_active
        
        # Recency: days since last order
        last_order = max(orders, key=lambda o: o.created_at)
        recency_days = (datetime.utcnow() - last_order.created_at).days
        
        # Category diversity
        categories = set()
        for order in orders:
            for item in order.items:
                product = db.query(Product).filter(Product.id == item.product_id).first()
                if product:
                    categories.add(product.category)
        category_diversity = len(categories)
        
        # Average items per order
        total_items = sum(len(order.items) for order in orders)
        avg_items_per_order = total_items / total_orders if total_orders > 0 else 0
        
        # Return rate (cancelled orders)
        cancelled_orders = len([o for o in orders if o.status == "Cancelled"])
        return_rate = cancelled_orders / total_orders if total_orders > 0 else 0
        
        return {
            "total_orders": total_orders,
            "total_spent": total_spent,
            "avg_order_value": avg_order_value,
            "order_frequency": order_frequency,
            "recency_days": recency_days,
            "category_diversity": category_diversity,
            "avg_items_per_order": avg_items_per_order,
            "return_rate": return_rate
        }
    
    def _get_default_features(self) -> Dict[str, float]:
        """Default features for new customers"""
        return {
            "total_orders": 0,
            "total_spent": 0,
            "avg_order_value": 0,
            "order_frequency": 0,
            "recency_days": 999,
            "category_diversity": 0,
            "avg_items_per_order": 0,
            "return_rate": 0
        }
    
    def segment_customer(self, user_id: int, db: Session) -> str:
        """Segment a customer into one of predefined segments"""
        features = self.get_customer_features(user_id, db)
        
        # Segmentation logic
        if features["total_orders"] == 0:
            return "new_customer"
        
        if features["total_spent"] > 10000 and features["order_frequency"] > 2:
            return "vip_customer"
        
        if features["total_spent"] > 5000 and features["order_frequency"] > 1:
            return "high_value"
        
        if features["recency_days"] < 30 and features["order_frequency"] > 1:
            return "active_shopper"
        
        if features["recency_days"] > 90:
            return "at_risk"
        
        if features["category_diversity"] >= 3:
            return "explorer"
        
        if features["category_diversity"] == 1:
            return "niche_shopper"
        
        return "regular_customer"
    
    def get_segment_recommendations(self, segment: str) -> List[str]:
        """Get recommendations based on customer segment"""
        recommendations = {
            "new_customer": [
                "Welcome discount on first purchase",
                "Product recommendations based on popular items",
                "Free shipping on first order"
            ],
            "vip_customer": [
                "Exclusive early access to new arrivals",
                "Personal stylist recommendations",
                "Loyalty points multiplier"
            ],
            "high_value": [
                "Premium product recommendations",
                "Bundle deals for higher value",
                "Express shipping upgrade"
            ],
            "active_shopper": [
                "New arrivals in favorite categories",
                "Limited time offers",
                "Personalized sale alerts"
            ],
            "at_risk": [
                "Win-back discount offers",
                "Re-engagement campaigns",
                "Feedback requests"
            ],
            "explorer": [
                "Cross-category recommendations",
                "New category introductions",
                "Discovery bundles"
            ],
            "niche_shopper": [
                "Deep category recommendations",
                "Specialized collections",
                "Expert picks in favorite category"
            ],
            "regular_customer": [
                "Standard personalized recommendations",
                "Seasonal promotions",
                "Flash sale notifications"
            ]
        }
        
        return recommendations.get(segment, [])
    
    def get_all_customer_segments(self, db: Session) -> Dict[str, int]:
        """Get distribution of customers across segments"""
        users = db.query(User).all()
        
        segment_counts = {
            "new_customer": 0,
            "vip_customer": 0,
            "high_value": 0,
            "active_shopper": 0,
            "at_risk": 0,
            "explorer": 0,
            "niche_shopper": 0,
            "regular_customer": 0
        }
        
        for user in users:
            segment = self.segment_customer(user.id, db)
            segment_counts[segment] = segment_counts.get(segment, 0) + 1
        
        return segment_counts


customer_segmentation_service = CustomerSegmentationService()
