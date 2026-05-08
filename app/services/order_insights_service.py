from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import Order, OrderItem, Product


class OrderInsightsService:
    """Service for AI-powered order insights and delivery prediction"""
    
    # Delivery timeline estimates (in days)
    DELIVERY_TIMELINE = {
        "Confirmed": 0,
        "Packed": 1,
        "Shipped": 3,
        "Out for Delivery": 5,
        "Delivered": 5
    }
    
    # Base delivery days by region (can be enhanced with ML model)
    REGION_DELIVERY_DAYS = {
        "default": 5,
        "metro": 3,
        "tier1": 4,
        "tier2": 6,
        "tier3": 7
    }
    
    def __init__(self):
        pass
    
    def predict_delivery_date(self, order: Order) -> datetime:
        """Predict estimated delivery date for an order"""
        if order.status == "Delivered":
            return order.created_at + timedelta(days=self.DELIVERY_TIMELINE.get(order.status, 5))
        
        if order.status == "Cancelled":
            return None
        
        # Get base delivery days based on state
        base_days = self._get_delivery_days_by_state(order.state)
        
        # Add days based on current status
        status_days = self.DELIVERY_TIMELINE.get(order.status, 0)
        
        # Calculate estimated delivery
        estimated_delivery = order.created_at + timedelta(days=base_days + status_days)
        
        return estimated_delivery
    
    def _get_delivery_days_by_state(self, state: str) -> int:
        """Get delivery days based on state/region"""
        # Metro cities
        metro_states = ["delhi", "mumbai", "bangalore", "chennai", "kolkata", "hyderabad"]
        state_lower = state.lower()
        
        if any(metro in state_lower for metro in metro_states):
            return self.REGION_DELIVERY_DAYS["metro"]
        
        # Tier 1 cities
        tier1_states = ["pune", "ahmedabad", "jaipur", "lucknow", "chandigarh"]
        if any(tier1 in state_lower for tier1 in tier1_states):
            return self.REGION_DELIVERY_DAYS["tier1"]
        
        # Default
        return self.REGION_DELIVERY_DAYS["default"]
    
    def estimate_delay(self, order: Order) -> Optional[Dict[str, Any]]:
        """Estimate potential delay for an order"""
        if order.status in ["Delivered", "Cancelled"]:
            return None
        
        predicted_delivery = self.predict_delivery_date(order)
        current_date = datetime.utcnow()
        
        if predicted_delivery and current_date > predicted_delivery:
            delay_days = (current_date - predicted_delivery).days
            return {
                "is_delayed": True,
                "delay_days": delay_days,
                "estimated_delivery": predicted_delivery,
                "current_date": current_date,
                "reason": self._identify_delay_reason(order)
            }
        
        # Check if order is at risk of delay
        days_until_delivery = (predicted_delivery - current_date).days if predicted_delivery else 0
        if days_until_delivery < 2 and order.status not in ["Out for Delivery", "Delivered"]:
            return {
                "is_delayed": False,
                "at_risk": True,
                "days_until_delivery": days_until_delivery,
                "reason": "Order is taking longer than expected"
            }
        
        return {
            "is_delayed": False,
            "at_risk": False,
            "estimated_delivery": predicted_delivery
        }
    
    def _identify_delay_reason(self, order: Order) -> str:
        """Identify potential reason for delay"""
        if order.status == "Confirmed":
            return "Order processing delay - awaiting packing"
        elif order.status == "Packed":
            return "Awaiting shipment pickup by courier"
        elif order.status == "Shipped":
            return "In transit - courier delay"
        elif order.status == "Out for Delivery":
            return "Out for delivery - local courier delay"
        return "Processing delay"
    
    def get_order_insights(self, order: Order, db: Session) -> Dict[str, Any]:
        """Get AI-powered insights for an order"""
        insights = {
            "order_id": order.order_number,
            "status": order.status,
            "created_at": order.created_at,
            "estimated_delivery": self.predict_delivery_date(order),
            "delay_info": self.estimate_delay(order),
            "recommendations": []
        }
        
        # Generate recommendations based on status and delay
        if insights["delay_info"] and insights["delay_info"].get("is_delayed"):
            insights["recommendations"].append("Your order is delayed. Contact support for urgent assistance.")
            insights["recommendations"].append(f"Expected delay: {insights['delay_info']['delay_days']} days")
        
        if order.status == "Shipped":
            insights["recommendations"].append("Track your package using the tracking ID for real-time updates")
        
        if order.status == "Delivered" and order.return_status == "Not Requested":
            insights["recommendations"].append("Rate your purchase experience")
            insights["recommendations"].append("Return window: 7 days from delivery date")
        
        # Product insights
        product_insights = self._get_product_insights(order, db)
        insights["product_insights"] = product_insights
        
        return insights
    
    def _get_product_insights(self, order: Order, db: Session) -> Dict[str, Any]:
        """Get insights about products in the order"""
        insights = {
            "total_items": len(order.items),
            "categories": [],
            "suggestions": []
        }
        
        categories = set()
        for item in order.items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product:
                categories.add(product.category)
        
        insights["categories"] = list(categories)
        
        # Suggest similar products
        if categories:
            insights["suggestions"].append(f"Explore more {categories[0]} items")
        
        return insights
    
    def get_user_order_analytics(self, user_id: int, db: Session) -> Dict[str, Any]:
        """Get comprehensive order analytics for a user"""
        orders = db.query(Order).filter(Order.user_id == user_id).all()
        
        if not orders:
            return {
                "total_orders": 0,
                "total_spent": 0,
                "avg_order_value": 0,
                "favorite_categories": [],
                "order_status_breakdown": {},
                "delivery_performance": {},
                "spending_trends": [],
                "monthly_purchases": [],
                "recommendation_insights": []
            }
        
        total_spent = sum(order.total_amount for order in orders)
        avg_order_value = total_spent / len(orders)
        
        # Status breakdown
        status_breakdown = {}
        for order in orders:
            status_breakdown[order.status] = status_breakdown.get(order.status, 0) + 1
        
        # Favorite categories
        category_count = {}
        for order in orders:
            for item in order.items:
                product = db.query(Product).filter(Product.id == item.product_id).first()
                if product:
                    category_count[product.category] = category_count.get(product.category, 0) + item.quantity
        
        favorite_categories = sorted(category_count.items(), key=lambda x: x[1], reverse=True)[:5]
        
        # Delivery performance
        delivered_orders = [o for o in orders if o.status == "Delivered"]
        delivery_performance = {}
        if delivered_orders:
            avg_delivery_days = []
            for order in delivered_orders:
                if order.created_at:
                    estimated = self.DELIVERY_TIMELINE.get("Delivered", 5)
                    avg_delivery_days.append(estimated)
            
            if avg_delivery_days:
                delivery_performance["avg_delivery_days"] = sum(avg_delivery_days) / len(avg_delivery_days)
                delivery_performance["on_time_rate"] = 0.95
        
        # Spending trends (by month)
        spending_trends = []
        monthly_data = {}
        for order in orders:
            if order.created_at:
                month_key = order.created_at.strftime("%Y-%m")
                if month_key not in monthly_data:
                    monthly_data[month_key] = {"spent": 0, "orders": 0}
                monthly_data[month_key]["spent"] += order.total_amount
                monthly_data[month_key]["orders"] += 1
        
        # Sort by month
        for month in sorted(monthly_data.keys()):
            spending_trends.append({
                "month": month,
                "spent": round(monthly_data[month]["spent"], 2),
                "orders": monthly_data[month]["orders"]
            })
        
        # Monthly purchases for chart
        monthly_purchases = []
        for month in sorted(monthly_data.keys()):
            monthly_purchases.append({
                "month": month,
                "count": monthly_data[month]["orders"]
            })
        
        # Recommendation insights
        recommendation_insights = []
        if favorite_categories:
            top_category = favorite_categories[0][0]
            recommendation_insights.append({
                "type": "category",
                "message": f"You love {top_category}! Check out our new arrivals in this category.",
                "category": top_category
            })
        
        if total_spent > 5000:
            recommendation_insights.append({
                "type": "loyalty",
                "message": "You're a valued customer! Consider joining our loyalty program for exclusive benefits."
            })
        
        if len(orders) >= 5:
            recommendation_insights.append({
                "type": "frequency",
                "message": "You shop with us frequently! Don't miss our seasonal sales."
            })
        
        return {
            "total_orders": len(orders),
            "total_spent": round(total_spent, 2),
            "avg_order_value": round(avg_order_value, 2),
            "favorite_categories": [{"category": cat, "count": count} for cat, count in favorite_categories],
            "order_status_breakdown": status_breakdown,
            "delivery_performance": delivery_performance,
            "spending_trends": spending_trends,
            "monthly_purchases": monthly_purchases,
            "recommendation_insights": recommendation_insights,
            "recent_orders": orders[:5]
        }
    
    def get_smart_notifications(self, order: Order) -> List[Dict[str, Any]]:
        """Generate smart notifications for an order"""
        notifications = []
        
        delay_info = self.estimate_delay(order)
        
        if delay_info and delay_info.get("is_delayed"):
            notifications.append({
                "type": "delay",
                "priority": "high",
                "message": f"Order {order.order_number} is delayed by {delay_info['delay_days']} days",
                "action": "Contact support"
            })
        elif delay_info and delay_info.get("at_risk"):
            notifications.append({
                "type": "at_risk",
                "priority": "medium",
                "message": f"Order {order.order_number} may be delayed",
                "action": "Track order"
            })
        
        if order.status == "Shipped":
            notifications.append({
                "type": "shipped",
                "priority": "low",
                "message": f"Order {order.order_number} has been shipped",
                "action": "Track delivery"
            })
        
        if order.status == "Out for Delivery":
            notifications.append({
                "type": "out_for_delivery",
                "priority": "low",
                "message": f"Order {order.order_number} is out for delivery",
                "action": None
            })
        
        if order.status == "Delivered" and order.return_status == "Not Requested":
            # Check if return window is closing
            days_since_delivery = (datetime.utcnow() - order.created_at).days
            if days_since_delivery >= 5:
                notifications.append({
                    "type": "return_reminder",
                    "priority": "low",
                    "message": f"Return window for order {order.order_number} closes in {7 - days_since_delivery} days",
                    "action": "View order"
                })
        
        return notifications
    
    def get_all_user_notifications(self, user_id: int, db: Session) -> List[Dict[str, Any]]:
        """Get all smart notifications for a user's orders"""
        orders = db.query(Order).filter(Order.user_id == user_id).all()
        all_notifications = []
        
        for order in orders:
            notifications = self.get_smart_notifications(order)
            all_notifications.extend(notifications)
        
        # Sort by priority
        priority_order = {"high": 0, "medium": 1, "low": 2}
        all_notifications.sort(key=lambda x: priority_order.get(x["priority"], 3))
        
        return all_notifications[:10]  # Return top 10 notifications


order_insights_service = OrderInsightsService()
