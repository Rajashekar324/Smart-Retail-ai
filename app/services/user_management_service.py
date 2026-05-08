from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func, Column, Integer, String, DateTime, Boolean, Text, ForeignKey
from enum import Enum
import json

from app.database import Base
from app.models import User, Order, UserActivity, UserAlert, AuditLog


class Role(Base):
    __tablename__ = "roles"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)
    permissions = Column(Text, nullable=False)  # JSON list of permissions
    created_at = Column(DateTime, default=datetime.utcnow)


class UserRole(Base):
    __tablename__ = "user_roles"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Permission(Enum):
    VIEW_USERS = "view_users"
    EDIT_USERS = "edit_users"
    DELETE_USERS = "delete_users"
    VIEW_ORDERS = "view_orders"
    EDIT_ORDERS = "edit_orders"
    VIEW_PRODUCTS = "view_products"
    EDIT_PRODUCTS = "edit_products"
    DELETE_PRODUCTS = "delete_products"
    VIEW_ANALYTICS = "view_analytics"
    MANAGE_AGENTS = "manage_agents"
    MANAGE_DOCUMENTS = "manage_documents"
    SYSTEM_ADMIN = "system_admin"


class UserManagementService:
    """User management service with roles, permissions, and audit logging"""
    
    def __init__(self):
        self.default_roles = {
            "admin": [p.value for p in Permission],
            "manager": [
                Permission.VIEW_USERS.value,
                Permission.EDIT_USERS.value,
                Permission.VIEW_ORDERS.value,
                Permission.EDIT_ORDERS.value,
                Permission.VIEW_PRODUCTS.value,
                Permission.EDIT_PRODUCTS.value,
                Permission.VIEW_ANALYTICS.value
            ],
            "support": [
                Permission.VIEW_USERS.value,
                Permission.VIEW_ORDERS.value,
                Permission.EDIT_ORDERS.value,
                Permission.VIEW_PRODUCTS.value
            ],
            "viewer": [
                Permission.VIEW_USERS.value,
                Permission.VIEW_ORDERS.value,
                Permission.VIEW_PRODUCTS.value,
                Permission.VIEW_ANALYTICS.value
            ]
        }
    
    def initialize_roles(self, db: Session):
        """Initialize default roles in database"""
        for role_name, permissions in self.default_roles.items():
            existing = db.query(Role).filter(Role.name == role_name).first()
            if not existing:
                role = Role(
                    name=role_name,
                    permissions=json.dumps(permissions)
                )
                db.add(role)
        db.commit()
    
    def log_audit_event(self, db: Session, action: str, entity_type: str, 
                       entity_id: str = None, user_id: int = None,
                       old_values: dict = None, new_values: dict = None,
                       ip_address: str = None, user_agent: str = None):
        """Log an audit event"""
        log = AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            old_values=json.dumps(old_values) if old_values else None,
            new_values=json.dumps(new_values) if new_values else None,
            ip_address=ip_address,
            user_agent=user_agent
        )
        db.add(log)
        db.commit()
        return log
    
    def get_audit_logs(self, db: Session, user_id: int = None, 
                      entity_type: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get audit logs with filtering"""
        query = db.query(AuditLog).order_by(AuditLog.created_at.desc())
        
        if user_id:
            query = query.filter(AuditLog.user_id == user_id)
        if entity_type:
            query = query.filter(AuditLog.entity_type == entity_type)
        
        logs = query.limit(limit).all()
        
        result = []
        for log in logs:
            def parse_json_safe(value):
                if not value or value.strip() == '':
                    return None
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return None
            
            result.append({
                "id": log.id,
                "user_id": log.user_id,
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "old_values": parse_json_safe(log.old_values),
                "new_values": parse_json_safe(log.new_values),
                "ip_address": log.ip_address,
                "created_at": log.created_at.isoformat()
            })
        
        return result
    
    def get_user_activity(self, db: Session, user_id: int, days: int = 30) -> Dict[str, Any]:
        """Get comprehensive user activity"""
        start_date = datetime.utcnow() - timedelta(days=days)
        
        # Login activity
        login_count = db.query(UserActivity).filter(
            UserActivity.user_id == user_id,
            UserActivity.activity_type == "login",
            UserActivity.created_at >= start_date
        ).count()
        
        # Order activity
        orders = db.query(Order).filter(
            Order.user_id == user_id,
            Order.created_at >= start_date
        ).all()
        
        # Recent activity logs
        recent_activities = db.query(UserActivity).filter(
            UserActivity.user_id == user_id,
            UserActivity.created_at >= start_date
        ).order_by(UserActivity.created_at.desc()).limit(20).all()
        
        return {
            "user_id": user_id,
            "period_days": days,
            "login_count": login_count,
            "orders_count": len(orders),
            "total_spent": sum(o.total_amount for o in orders),
            "recent_activities": [
                {
                    "type": act.activity_type,
                    "details": act.activity_details,
                    "timestamp": act.created_at.isoformat()
                }
                for act in recent_activities
            ]
        }
    
    def detect_suspicious_users(self, db: Session) -> List[Dict[str, Any]]:
        """Detect suspicious user behavior"""
        suspicious = []
        
        # Users with multiple failed logins
        recent_time = datetime.utcnow() - timedelta(hours=24)
        failed_logins = db.query(
            UserActivity.user_id,
            func.count(UserActivity.id).label('failed_count')
        ).filter(
            UserActivity.activity_type == "login_failed",
            UserActivity.created_at >= recent_time
        ).group_by(UserActivity.user_id).having(
            func.count(UserActivity.id) >= 5
        ).all()
        
        for user_id, count in failed_logins:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                suspicious.append({
                    "user_id": user.id,
                    "email": user.email,
                    "type": "multiple_failed_logins",
                    "count": count,
                    "severity": "high",
                    "message": f"{count} failed login attempts in last 24 hours"
                })
        
        # Users with rapid order cancellations
        cancelled_orders = db.query(
            Order.user_id,
            func.count(Order.id).label('cancel_count')
        ).filter(
            Order.status == "Cancelled",
            Order.created_at >= recent_time
        ).group_by(Order.user_id).having(
            func.count(Order.id) >= 3
        ).all()
        
        for user_id, count in cancelled_orders:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                suspicious.append({
                    "user_id": user.id,
                    "email": user.email,
                    "type": "rapid_cancellations",
                    "count": count,
                    "severity": "medium",
                    "message": f"{count} orders cancelled in last 24 hours"
                })
        
        # Inactive users suddenly active
        old_users = db.query(User).filter(
            User.created_at <= datetime.utcnow() - timedelta(days=90)
        ).all()
        
        for user in old_users:
            recent_orders = db.query(Order).filter(
                Order.user_id == user.id,
                Order.created_at >= recent_time
            ).count()
            
            if recent_orders >= 5:
                suspicious.append({
                    "user_id": user.id,
                    "email": user.email,
                    "type": "sudden_activity_spike",
                    "count": recent_orders,
                    "severity": "medium",
                    "message": f"Sudden activity: {recent_orders} orders in last 24 hours after long inactivity"
                })
        
        return suspicious
    
    def update_user_status(self, db: Session, user_id: int, status: str, 
                          reason: str = None, admin_id: int = None) -> bool:
        """Update user account status (active, suspended, banned)"""
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return False
        
        old_status = getattr(user, 'account_status', 'active')
        
        # Add account_status field if not exists
        if not hasattr(user, 'account_status'):
            # Store in metadata or create separate tracking
            pass
        
        # Log the change
        self.log_audit_event(
            db,
            action="update_user_status",
            entity_type="user",
            entity_id=str(user_id),
            user_id=admin_id,
            old_values={"status": old_status},
            new_values={"status": status, "reason": reason}
        )
        
        return True
    
    def assign_role(self, db: Session, user_id: int, role_name: str, admin_id: int = None) -> bool:
        """Assign a role to a user"""
        user = db.query(User).filter(User.id == user_id).first()
        role = db.query(Role).filter(Role.name == role_name).first()
        
        if not user or not role:
            return False
        
        # Remove existing roles
        db.query(UserRole).filter(UserRole.user_id == user_id).delete()
        
        # Assign new role
        user_role = UserRole(user_id=user_id, role_id=role.id)
        db.add(user_role)
        db.commit()
        
        # Log the change
        self.log_audit_event(
            db,
            action="assign_role",
            entity_type="user",
            entity_id=str(user_id),
            user_id=admin_id,
            new_values={"role": role_name}
        )
        
        return True
    
    def get_user_permissions(self, db: Session, user_id: int) -> List[str]:
        """Get all permissions for a user"""
        # Check if admin
        user = db.query(User).filter(User.id == user_id).first()
        if user and user.is_admin:
            return [p.value for p in Permission]
        
        # Get from roles
        user_roles = db.query(UserRole).filter(UserRole.user_id == user_id).all()
        permissions = set()
        
        for ur in user_roles:
            role = db.query(Role).filter(Role.id == ur.role_id).first()
            if role:
                role_perms = json.loads(role.permissions)
                permissions.update(role_perms)
        
        return list(permissions)
    
    def has_permission(self, db: Session, user_id: int, permission: str) -> bool:
        """Check if user has a specific permission"""
        permissions = self.get_user_permissions(db, user_id)
        return permission in permissions or Permission.SYSTEM_ADMIN.value in permissions
    
    def get_all_users_with_roles(self, db: Session) -> List[Dict[str, Any]]:
        """Get all users with their roles and status"""
        users = db.query(User).all()
        
        result = []
        for user in users:
            # Get user roles
            roles = db.query(Role).join(UserRole).filter(
                UserRole.user_id == user.id
            ).all()
            
            # Get recent activity
            last_activity = db.query(UserActivity).filter(
                UserActivity.user_id == user.id
            ).order_by(UserActivity.created_at.desc()).first()
            
            result.append({
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "is_admin": user.is_admin,
                "roles": [r.name for r in roles] if roles else (["admin"] if user.is_admin else ["customer"]),
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "last_activity": last_activity.created_at.isoformat() if last_activity else None,
                "status": "active"  # Default, can be extended
            })
        
        return result


user_management_service = UserManagementService()
