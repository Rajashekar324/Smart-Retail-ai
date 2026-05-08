from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from collections import Counter

from app.models import Order, OrderItem, Product, User, SupportTicket


class AdminAnalyticsService:
    """Enterprise-grade admin analytics service"""
    
    def __init__(self):
        pass
    
    def get_dashboard_metrics(self, db: Session) -> Dict[str, Any]:
        """Get comprehensive dashboard metrics"""
        # Total revenue
        total_revenue = db.query(func.sum(Order.total_amount)).scalar() or 0
        
        # Total orders
        total_orders = db.query(Order).count()
        
        # Total customers
        total_customers = db.query(User).count()
        
        # Total products
        total_products = db.query(Product).count()
        
        # Profit (simplified: 20% of revenue)
        profit = total_revenue * 0.2
        
        # Average order value
        avg_order_value = total_revenue / total_orders if total_orders > 0 else 0
        
        # Today's revenue
        today = datetime.utcnow().date()
        today_revenue = db.query(func.sum(Order.total_amount)).filter(
            func.date(Order.created_at) == today
        ).scalar() or 0
        
        # Today's orders
        today_orders = db.query(Order).filter(
            func.date(Order.created_at) == today
        ).count()
        
        # Active users (last 30 days)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        active_users = db.query(Order).filter(
            Order.created_at >= thirty_days_ago
        ).distinct(Order.user_id).count()
        
        return {
            "total_revenue": round(total_revenue, 2),
            "total_orders": total_orders,
            "total_customers": total_customers,
            "total_products": total_products,
            "profit": round(profit, 2),
            "avg_order_value": round(avg_order_value, 2),
            "today_revenue": round(today_revenue, 2),
            "today_orders": today_orders,
            "active_users": active_users
        }
    
    def get_revenue_trends(self, db: Session, days: int = 30) -> List[Dict[str, Any]]:
        """Get revenue trends over time"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        trends = []
        for i in range(days):
            date = start_date + timedelta(days=i)
            revenue = db.query(func.sum(Order.total_amount)).filter(
                func.date(Order.created_at) == date.date()
            ).scalar() or 0
            
            orders = db.query(Order).filter(
                func.date(Order.created_at) == date.date()
            ).count()
            
            trends.append({
                "date": date.strftime("%Y-%m-%d"),
                "revenue": round(revenue, 2),
                "orders": orders
            })
        
        return trends
    
    def get_customer_growth(self, db: Session, months: int = 6) -> List[Dict[str, Any]]:
        """Get customer growth over months"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=months * 30)
        
        growth = []
        for i in range(months):
            month_start = start_date + timedelta(days=i * 30)
            month_end = month_start + timedelta(days=30)
            
            new_customers = db.query(User).filter(
                User.created_at >= month_start,
                User.created_at < month_end
            ).count()
            
            growth.append({
                "month": month_start.strftime("%Y-%m"),
                "new_customers": new_customers
            })
        
        return growth
    
    def get_top_selling_products(self, db: Session, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top-selling products"""
        result = db.query(
            Product.id,
            Product.name,
            Product.category,
            Product.price,
            func.sum(OrderItem.quantity).label('total_sold'),
            func.sum(OrderItem.quantity * OrderItem.unit_price).label('total_revenue')
        ).join(OrderItem, Product.id == OrderItem.product_id)\
         .group_by(Product.id)\
         .order_by(func.sum(OrderItem.quantity).desc())\
         .limit(limit)\
         .all()
        
        products = []
        for row in result:
            products.append({
                "id": row.id,
                "name": row.name,
                "category": row.category,
                "price": row.price,
                "total_sold": row.total_sold or 0,
                "total_revenue": round(row.total_revenue or 0, 2)
            })
        
        return products
    
    def get_low_stock_alerts(self, db: Session, threshold: int = 5) -> List[Dict[str, Any]]:
        """Get products with low stock"""
        products = db.query(Product).filter(Product.stock <= threshold).all()
        
        alerts = []
        for product in products:
            alerts.append({
                "id": product.id,
                "name": product.name,
                "category": product.category,
                "stock": product.stock,
                "price": product.price,
                "severity": "critical" if product.stock == 0 else "warning"
            })
        
        return alerts
    
    def get_inventory_trends(self, db: Session, days: int = 30) -> List[Dict[str, Any]]:
        """Get inventory trends over time"""
        # Simplified - show current inventory by category
        categories = db.query(Product.category).distinct().all()
        
        trends = []
        for cat in categories:
            total_stock = db.query(func.sum(Product.stock)).filter(
                Product.category == cat[0]
            ).scalar() or 0
            
            total_products = db.query(Product).filter(
                Product.category == cat[0]
            ).count()
            
            trends.append({
                "category": cat[0],
                "total_stock": total_stock,
                "total_products": total_products
            })
        
        return sorted(trends, key=lambda x: x["total_stock"])
    
    def get_order_status_breakdown(self, db: Session) -> Dict[str, int]:
        """Get order status breakdown"""
        statuses = ["Confirmed", "Packed", "Shipped", "Out for Delivery", "Delivered", "Cancelled", "Returned"]
        
        breakdown = {}
        for status in statuses:
            count = db.query(Order).filter(Order.status == status).count()
            breakdown[status] = count
        
        return breakdown
    
    def get_ai_insights(self, db: Session) -> List[str]:
        """Generate AI-powered insights from data"""
        insights = []
        
        # Revenue insight
        total_revenue = db.query(func.sum(Order.total_amount)).scalar() or 0
        if total_revenue > 100000:
            insights.append("Revenue exceeded ₹1L this month - strong performance")
        
        # Order volume insight
        total_orders = db.query(Order).count()
        if total_orders > 500:
            insights.append("Order volume is high - consider scaling operations")
        
        # Low stock insight
        low_stock = db.query(Product).filter(Product.stock < 5).count()
        if low_stock > 10:
            insights.append(f"{low_stock} products are running low on stock - urgent restocking needed")
        
        # Customer retention insight
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        repeat_customers = db.query(Order).filter(
            Order.created_at >= thirty_days_ago
        ).distinct(Order.user_id).count()
        
        if repeat_customers > 50:
            insights.append("High customer retention rate - loyalty programs effective")
        
        # Profit margin insight
        if total_revenue > 0:
            profit = total_revenue * 0.2
            margin = (profit / total_revenue) * 100
            if margin < 15:
                insights.append("Profit margin below 15% - review pricing strategy")
        
        # Support tickets insight
        pending_tickets = db.query(SupportTicket).filter(
            SupportTicket.status == "Open"
        ).count()
        
        if pending_tickets > 20:
            insights.append(f"{pending_tickets} pending support tickets - allocate more resources")
        
        return insights
    
    def get_anomaly_alerts(self, db: Session) -> List[Dict[str, Any]]:
        """Detect anomalies in data"""
        alerts = []
        
        # Revenue anomaly
        today = datetime.utcnow().date()
        yesterday = today - timedelta(days=1)
        
        today_revenue = db.query(func.sum(Order.total_amount)).filter(
            func.date(Order.created_at) == today
        ).scalar() or 0
        
        yesterday_revenue = db.query(func.sum(Order.total_amount)).filter(
            func.date(Order.created_at) == yesterday
        ).scalar() or 0
        
        if yesterday_revenue > 0:
            change_percent = ((today_revenue - yesterday_revenue) / yesterday_revenue) * 100
            if abs(change_percent) > 50:
                alerts.append({
                    "type": "revenue_anomaly",
                    "severity": "high",
                    "message": f"Revenue changed by {change_percent:.1f}% compared to yesterday",
                    "value": round(today_revenue, 2)
                })
        
        # Order volume anomaly
        today_orders = db.query(Order).filter(
            func.date(Order.created_at) == today
        ).count()
        
        yesterday_orders = db.query(Order).filter(
            func.date(Order.created_at) == yesterday
        ).count()
        
        if yesterday_orders > 0:
            change_percent = ((today_orders - yesterday_orders) / yesterday_orders) * 100
            if abs(change_percent) > 50:
                alerts.append({
                    "type": "order_anomaly",
                    "severity": "medium",
                    "message": f"Order volume changed by {change_percent:.1f}% compared to yesterday",
                    "value": today_orders
                })
        
        # Cancellation rate anomaly
        total_orders_today = db.query(Order).filter(
            func.date(Order.created_at) == today
        ).count()
        
        cancelled_today = db.query(Order).filter(
            func.date(Order.created_at) == today,
            Order.status == "Cancelled"
        ).count()
        
        if total_orders_today > 0:
            cancellation_rate = (cancelled_today / total_orders_today) * 100
            if cancellation_rate > 20:
                alerts.append({
                    "type": "cancellation_anomaly",
                    "severity": "high",
                    "message": f"High cancellation rate: {cancellation_rate:.1f}% today",
                    "value": round(cancellation_rate, 2)
                })
        
        return alerts
    
    def get_comprehensive_dashboard(self, db: Session) -> Dict[str, Any]:
        """Get complete dashboard data"""
        return {
            "metrics": self.get_dashboard_metrics(db),
            "revenue_trends": self.get_revenue_trends(db, days=30),
            "customer_growth": self.get_customer_growth(db, months=6),
            "top_selling_products": self.get_top_selling_products(db, limit=10),
            "low_stock_alerts": self.get_low_stock_alerts(db, threshold=5),
            "inventory_trends": self.get_inventory_trends(db),
            "order_status_breakdown": self.get_order_status_breakdown(db),
            "ai_insights": self.get_ai_insights(db),
            "anomaly_alerts": self.get_anomaly_alerts(db)
        }


admin_analytics_service = AdminAnalyticsService()
