from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, Float
from sqlalchemy.ext.declarative import declarative_base

from app.models import Product, Order

Base = declarative_base()


class UserAlert(Base):
    __tablename__ = "user_alerts"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    alert_type = Column(String(50), nullable=False)  # stock, price_drop, recommendation, order
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    product_id = Column(Integer, nullable=True)
    order_id = Column(String(100), nullable=True)
    is_read = Column(Boolean, default=False)
    priority = Column(String(20), default="medium")  # high, medium, low
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    action_url = Column(String(500), nullable=True)
    meta_data = Column(Text, nullable=True)  # JSON string for additional data


class UserAlertsService:
    """User alerts service for stock, price drops, recommendations, and order notifications"""
    
    def __init__(self):
        pass
    
    def create_stock_alert(self, user_id: int, product_id: int, db: Session) -> UserAlert:
        """Create a stock availability alert"""
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            return None
        
        alert = UserAlert(
            user_id=user_id,
            alert_type="stock",
            title=f"{product.name} is back in stock!",
            message=f"Good news! {product.name} is now available. Limited stock remaining.",
            product_id=product_id,
            priority="high",
            expires_at=datetime.utcnow() + timedelta(days=7),
            action_url=f"/product/{product_id}"
        )
        
        db.add(alert)
        db.commit()
        db.refresh(alert)
        return alert
    
    def create_price_drop_alert(self, user_id: int, product_id: int, old_price: float, new_price: float, db: Session) -> UserAlert:
        """Create a price drop alert"""
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            return None
        
        discount_percent = round(((old_price - new_price) / old_price) * 100, 2)
        
        alert = UserAlert(
            user_id=user_id,
            alert_type="price_drop",
            title=f"Price drop on {product.name}!",
            message=f"The price of {product.name} has dropped by {discount_percent}% from ₹{old_price:.0f} to ₹{new_price:.0f}",
            product_id=product_id,
            priority="high" if discount_percent > 20 else "medium",
            expires_at=datetime.utcnow() + timedelta(days=3),
            action_url=f"/product/{product_id}"
        )
        
        db.add(alert)
        db.commit()
        db.refresh(alert)
        return alert
    
    def create_recommendation_alert(self, user_id: int, message: str, product_id: int = None, db: Session = None) -> UserAlert:
        """Create an AI recommendation alert"""
        if db is None:
            return None
        
        alert = UserAlert(
            user_id=user_id,
            alert_type="recommendation",
            title="Recommended for you",
            message=message,
            product_id=product_id,
            priority="low",
            expires_at=datetime.utcnow() + timedelta(days=14),
            action_url=f"/product/{product_id}" if product_id else None
        )
        
        db.add(alert)
        db.commit()
        db.refresh(alert)
        return alert
    
    def create_order_alert(self, user_id: int, order_id: str, message: str, priority: str = "medium", db: Session = None) -> UserAlert:
        """Create an order notification alert"""
        if db is None:
            return None
        
        alert = UserAlert(
            user_id=user_id,
            alert_type="order",
            title="Order Update",
            message=message,
            order_id=order_id,
            priority=priority,
            expires_at=datetime.utcnow() + timedelta(days=30),
            action_url=f"/orders/{order_id}"
        )
        
        db.add(alert)
        db.commit()
        db.refresh(alert)
        return alert
    
    def get_user_alerts(self, user_id: int, db: Session, unread_only: bool = False, limit: int = 50) -> List[Dict[str, Any]]:
        """Get alerts for a user"""
        query = db.query(UserAlert).filter(UserAlert.user_id == user_id)
        
        if unread_only:
            query = query.filter(UserAlert.is_read == False)
        
        # Filter expired alerts
        query = query.filter(
            (UserAlert.expires_at == None) | (UserAlert.expires_at > datetime.utcnow())
        )
        
        alerts = query.order_by(UserAlert.created_at.desc()).limit(limit).all()
        
        result = []
        for alert in alerts:
            result.append({
                "id": alert.id,
                "alert_type": alert.alert_type,
                "title": alert.title,
                "message": alert.message,
                "product_id": alert.product_id,
                "order_id": alert.order_id,
                "is_read": alert.is_read,
                "priority": alert.priority,
                "created_at": alert.created_at.isoformat() if alert.created_at else None,
                "action_url": alert.action_url
            })
        
        return result
    
    def mark_as_read(self, alert_id: int, db: Session) -> bool:
        """Mark an alert as read"""
        alert = db.query(UserAlert).filter(UserAlert.id == alert_id).first()
        if alert:
            alert.is_read = True
            db.commit()
            return True
        return False
    
    def mark_all_as_read(self, user_id: int, db: Session) -> int:
        """Mark all alerts for a user as read"""
        alerts = db.query(UserAlert).filter(
            UserAlert.user_id == user_id,
            UserAlert.is_read == False
        ).all()
        
        count = 0
        for alert in alerts:
            alert.is_read = True
            count += 1
        
        db.commit()
        return count
    
    def delete_alert(self, alert_id: int, db: Session) -> bool:
        """Delete an alert"""
        alert = db.query(UserAlert).filter(UserAlert.id == alert_id).first()
        if alert:
            db.delete(alert)
            db.commit()
            return True
        return False
    
    def cleanup_expired_alerts(self, db: Session) -> int:
        """Clean up expired alerts"""
        expired = db.query(UserAlert).filter(
            UserAlert.expires_at < datetime.utcnow()
        ).all()
        
        count = len(expired)
        for alert in expired:
            db.delete(alert)
        
        db.commit()
        return count
    
    def check_price_drops_and_alert(self, db: Session):
        """Check for price drops and create alerts for interested users"""
        # This would need to track price history and user interests
        # For now, this is a placeholder for the implementation
        pass


user_alerts_service = UserAlertsService()
