from __future__ import annotations

from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session

from app.services.customer_segmentation_service import customer_segmentation_service
from app.services.behavior_analysis_service import behavior_analysis_service


class PersonalizationService:
    """Personalized banner and recommendation system"""
    
    def __init__(self):
        pass
    
    def get_personalized_banner(self, user_id: int, db: Session) -> Dict[str, Any]:
        """Get personalized banner based on customer segment and behavior"""
        segment = customer_segmentation_service.segment_customer(user_id, db)
        behavior = behavior_analysis_service.analyze_browsing_behavior(user_id, db)
        
        banners = {
            "new_customer": {
                "title": "Welcome to StyleHub AI!",
                "subtitle": "Get 20% off your first order",
                "cta": "Shop Now",
                "background": "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
                "icon": "🎉"
            },
            "vip_customer": {
                "title": "Exclusive VIP Access",
                "subtitle": "Early access to new collections just for you",
                "cta": "Explore VIP Collection",
                "background": "linear-gradient(135deg, #f093fb 0%, #f5576c 100%)",
                "icon": "👑"
            },
            "high_value": {
                "title": "Premium Picks for You",
                "subtitle": "Handpicked selections based on your style",
                "cta": "View Collection",
                "background": "linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)",
                "icon": "💎"
            },
            "active_shopper": {
                "title": "New Arrivals Alert",
                "subtitle": "Fresh styles just dropped in your favorites",
                "cta": "Shop New Arrivals",
                "background": "linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)",
                "icon": "🔥"
            },
            "at_risk": {
                "title": "We Miss You!",
                "subtitle": "Here's a special 15% off to welcome you back",
                "cta": "Claim Offer",
                "background": "linear-gradient(135deg, #fa709a 0%, #fee140 100%)",
                "icon": "💝"
            },
            "explorer": {
                "title": "Discover Something New",
                "subtitle": "Explore categories you haven't tried yet",
                "cta": "Discover",
                "background": "linear-gradient(135deg, #a8edea 0%, #fed6e3 100%)",
                "icon": "🧭"
            },
            "niche_shopper": {
                "title": "Expert Picks",
                "subtitle": "Curated selections in your favorite category",
                "cta": "View Picks",
                "background": "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
                "icon": "⭐"
            },
            "regular_customer": {
                "title": "Your Personalized Feed",
                "subtitle": "Recommendations based on your shopping history",
                "cta": "View Recommendations",
                "background": "linear-gradient(135deg, #89f7fe 0%, #66a6ff 100%)",
                "icon": "🛍️"
            }
        }
        
        banner = banners.get(segment, banners["regular_customer"])
        banner["segment"] = segment
        
        # Add time-based personalization
        hour = behavior.get("time_preference", "unknown")
        if hour == "morning":
            banner["subtitle"] = "Good morning! " + banner["subtitle"]
        elif hour == "evening":
            banner["subtitle"] = "Good evening! " + banner["subtitle"]
        
        return banner
    
    def get_dynamic_recommendations(self, user_id: int, db: Session, limit: int = 8) -> List[Dict[str, Any]]:
        """Get dynamic homepage recommendations based on behavior and segment"""
        from app.models import Product, Order, OrderItem
        from app.services.product_search_service import product_search_service
        
        segment = customer_segmentation_service.segment_customer(user_id, db)
        category_affinity = behavior_analysis_service.get_category_affinity(user_id, db)
        
        recommendations = []
        
        # Strategy based on segment
        if segment == "new_customer":
            # Show trending products
            products = db.query(Product).order_by(Product.stock.desc(), Product.created_at.desc()).limit(limit).all()
            recommendations = [{"product": p, "reason": "Trending Now"} for p in products]
        
        elif segment == "vip_customer" or segment == "high_value":
            # Show premium products
            products = db.query(Product).filter(Product.price > 2000).order_by(Product.created_at.desc()).limit(limit).all()
            recommendations = [{"product": p, "reason": "Premium Selection"} for p in products]
        
        elif segment == "active_shopper":
            # Show new arrivals in favorite categories
            if category_affinity:
                top_category = category_affinity[0]["category"]
                products = db.query(Product).filter(
                    Product.category == top_category
                ).order_by(Product.created_at.desc()).limit(limit).all()
                recommendations = [{"product": p, "reason": f"New in {top_category}"} for p in products]
            else:
                products = db.query(Product).order_by(Product.created_at.desc()).limit(limit).all()
                recommendations = [{"product": p, "reason": "New Arrivals"} for p in products]
        
        elif segment == "explorer":
            # Show products from diverse categories
            categories = db.query(Product.category).distinct().all()
            diverse_products = []
            for i, cat in enumerate(categories[:limit]):
                product = db.query(Product).filter(Product.category == cat[0]).order_by(Product.stock.desc()).first()
                if product:
                    diverse_products.append(product)
            recommendations = [{"product": p, "reason": f"Try {p.category}"} for p in diverse_products]
        
        else:
            # Show AI-powered semantic recommendations
            orders = db.query(Order).filter(Order.user_id == user_id).all()
            if orders:
                last_order = orders[-1]
                for item in last_order.items:
                    similar = product_search_service.get_similar_products(item.product_id, n_results=2, db=db)
                    for p in similar:
                        if len(recommendations) < limit:
                            recommendations.append({"product": p, "reason": "Similar to your purchase"})
            
            # Fill with trending if needed
            if len(recommendations) < limit:
                trending = db.query(Product).order_by(Product.stock.desc()).limit(limit - len(recommendations)).all()
                for p in trending:
                    recommendations.append({"product": p, "reason": "Trending"})
        
        return recommendations[:limit]
    
    def get_personalization_data(self, user_id: int, db: Session) -> Dict[str, Any]:
        """Get complete personalization data for the user"""
        segment = customer_segmentation_service.segment_customer(user_id, db)
        banner = self.get_personalized_banner(user_id, db)
        recommendations = self.get_dynamic_recommendations(user_id, db)
        behavior = behavior_analysis_service.get_personalization_insights(user_id, db)
        
        return {
            "segment": segment,
            "banner": banner,
            "recommendations": recommendations,
            "behavior": behavior
        }


personalization_service = PersonalizationService()
