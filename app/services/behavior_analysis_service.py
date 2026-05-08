from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
from collections import Counter

from app.models import Order, OrderItem, Product, CartItem, WishlistItem


class ShoppingBehaviorAnalysisService:
    """AI-powered shopping behavior analysis"""
    
    def __init__(self):
        pass
    
    def analyze_browsing_behavior(self, user_id: int, db: Session) -> Dict[str, Any]:
        """Analyze user's browsing and shopping patterns"""
        orders = db.query(Order).filter(Order.user_id == user_id).all()
        cart_items = db.query(CartItem).filter(CartItem.user_id == user_id).all()
        wishlist_items = db.query(WishlistItem).filter(WishlistItem.user_id == user_id).all()
        
        # Analyze preferred time of day for shopping
        order_hours = [order.created_at.hour for order in orders if order.created_at]
        if order_hours:
            peak_hour = Counter(order_hours).most_common(1)[0][0]
            time_preference = self._get_time_preference(peak_hour)
        else:
            time_preference = "unknown"
        
        # Cart abandonment rate
        if cart_items:
            total_added = len(cart_items)
            purchased_from_cart = sum(1 for order in orders for item in order.items 
                                     for cart in cart_items if cart.product_id == item.product_id)
            abandonment_rate = 1 - (purchased_from_cart / total_added) if total_added > 0 else 0
        else:
            abandonment_rate = 0
        
        # Wishlist to purchase conversion
        if wishlist_items:
            wishlist_products = [item.product_id for item in wishlist_items]
            purchased_from_wishlist = sum(1 for order in orders for item in order.items 
                                         if item.product_id in wishlist_products)
            wishlist_conversion = purchased_from_wishlist / len(wishlist_items) if wishlist_items else 0
        else:
            wishlist_conversion = 0
        
        return {
            "time_preference": time_preference,
            "cart_abandonment_rate": round(abandonment_rate * 100, 2),
            "wishlist_conversion_rate": round(wishlist_conversion * 100, 2),
            "avg_cart_size": len(cart_items),
            "wishlist_size": len(wishlist_items),
            "total_orders": len(orders)
        }
    
    def _get_time_preference(self, hour: int) -> str:
        """Get time preference label"""
        if 6 <= hour < 12:
            return "morning"
        elif 12 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 21:
            return "evening"
        else:
            return "night"
    
    def get_price_sensitivity(self, user_id: int, db: Session) -> str:
        """Analyze user's price sensitivity"""
        orders = db.query(Order).filter(Order.user_id == user_id).all()
        
        if not orders:
            return "unknown"
        
        avg_order_value = sum(order.total_amount for order in orders) / len(orders)
        
        if avg_order_value < 1000:
            return "budget_conscious"
        elif avg_order_value < 3000:
            return "moderate_spender"
        else:
            return "premium_shopper"
    
    def get_category_affinity(self, user_id: int, db: Session) -> List[Dict[str, Any]]:
        """Get user's category affinity scores"""
        orders = db.query(Order).filter(Order.user_id == user_id).all()
        
        category_scores = {}
        total_items = 0
        
        for order in orders:
            for item in order.items:
                product = db.query(Product).filter(Product.id == item.product_id).first()
                if product:
                    category_scores[product.category] = category_scores.get(product.category, 0) + item.quantity
                    total_items += item.quantity
        
        if not category_scores:
            return []
        
        # Calculate affinity scores
        affinity = []
        for category, count in category_scores.items():
            affinity_score = count / total_items if total_items > 0 else 0
            affinity.append({
                "category": category,
                "count": count,
                "affinity_score": round(affinity_score * 100, 2)
            })
        
        affinity.sort(key=lambda x: x["affinity_score"], reverse=True)
        return affinity
    
    def get_personalization_insights(self, user_id: int, db: Session) -> Dict[str, Any]:
        """Get comprehensive personalization insights"""
        behavior = self.analyze_browsing_behavior(user_id, db)
        price_sensitivity = self.get_price_sensitivity(user_id, db)
        category_affinity = self.get_category_affinity(user_id, db)
        
        insights = {
            "behavior": behavior,
            "price_sensitivity": price_sensitivity,
            "category_affinity": category_affinity,
            "recommendations": self._generate_recommendations(behavior, price_sensitivity, category_affinity)
        }
        
        return insights
    
    def _generate_recommendations(self, behavior: Dict, price_sensitivity: str, category_affinity: List) -> List[str]:
        """Generate personalized recommendations based on analysis"""
        recommendations = []
        
        # Based on price sensitivity
        if price_sensitivity == "budget_conscious":
            recommendations.append("Show budget-friendly options and discounts")
        elif price_sensitivity == "premium_shopper":
            recommendations.append("Highlight premium and exclusive products")
        
        # Based on cart abandonment
        if behavior["cart_abandonment_rate"] > 50:
            recommendations.append("Send cart abandonment reminders with incentives")
        
        # Based on wishlist conversion
        if behavior["wishlist_conversion_rate"] < 30:
            recommendations.append("Promote wishlist items with discounts")
        
        # Based on category affinity
        if category_affinity:
            top_category = category_affinity[0]["category"]
            recommendations.append(f"Prioritize {top_category} recommendations")
        
        # Based on time preference
        if behavior["time_preference"] != "unknown":
            recommendations.append(f"Send promotions during {behavior['time_preference']}")
        
        return recommendations


behavior_analysis_service = ShoppingBehaviorAnalysisService()
