from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
import json
import base64
import hmac
import hashlib
import logging
import requests
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import Order, OrderItem, Product, User, SupportTicket, UserActivity
from app.config import settings

logger = logging.getLogger(__name__)


class PowerBIService:
    """Power BI Embedded Analytics Service"""
    
    def __init__(self):
        self.dashboards = {
            "sales_analytics": {
                "id": "sales-analytics-001",
                "name": "Sales Analytics",
                "description": "Comprehensive sales performance analytics",
                "icon": "💰",
                "color": "#0078d4",
                "report_id": "sales-report-main",
                "dataset_id": "sales-dataset",
                "pages": ["Overview", "Trends", "Products", "Regions"],
                "filters": {
                    "date_range": "last_30_days",
                    "include_forecast": True
                }
            },
            "forecasting": {
                "id": "forecasting-001",
                "name": "Demand Forecasting",
                "description": "AI-powered demand and revenue forecasting",
                "icon": "📈",
                "color": "#107c10",
                "report_id": "forecasting-report",
                "dataset_id": "forecasting-dataset",
                "pages": ["Revenue Forecast", "Product Demand", "Seasonal Trends", "Accuracy"],
                "filters": {
                    "forecast_period": "30_days",
                    "models": ["prophet", "arima", "lstm"]
                }
            },
            "anomaly_detection": {
                "id": "anomaly-001",
                "name": "Anomaly Detection",
                "description": "Fraud detection and unusual pattern analysis",
                "icon": "🚨",
                "color": "#d83b01",
                "report_id": "anomaly-report",
                "dataset_id": "anomaly-dataset",
                "pages": ["Overview", "Fraud Patterns", "Transaction Anomalies", "User Behavior"],
                "filters": {
                    "sensitivity": "high",
                    "time_window": "24h"
                }
            },
            "customer_insights": {
                "id": "customer-001",
                "name": "Customer Insights",
                "description": "Customer segmentation and behavior analysis",
                "icon": "👥",
                "color": "#5c2d91",
                "report_id": "customer-report",
                "dataset_id": "customer-dataset",
                "pages": ["Segments", "Retention", "Lifetime Value", "Churn Risk"],
                "filters": {
                    "segment_types": ["vip", "active", "at_risk", "new"],
                    "include_predictions": True
                }
            },
            "inventory_analytics": {
                "id": "inventory-001",
                "name": "Inventory Analytics",
                "description": "Stock levels, turnover, and warehouse metrics",
                "icon": "📦",
                "color": "#ffb900",
                "report_id": "inventory-report",
                "dataset_id": "inventory-dataset",
                "pages": ["Stock Overview", "Turnover", "Shortage Predictions", "Warehouse"],
                "filters": {
                    "show_predictions": True,
                    "alert_threshold": 10
                }
            },
            "agent_analytics": {
                "id": "agent-001",
                "name": "AI Agent Analytics",
                "description": "Multi-agent system performance and health",
                "icon": "🤖",
                "color": "#00bcf2",
                "report_id": "agent-report",
                "dataset_id": "agent-dataset",
                "pages": ["Overview", "Task Execution", "Agent Health", "Orchestration"],
                "filters": {
                    "agents": ["inventory", "retail_analyst", "ml_insights", "document"],
                    "time_range": "24h"
                }
            }
        }
        
        # Azure Power BI configuration
        self.workspace_id = settings.azure_powerbi_workspace_id or "powerbi-workspace-stylehub"
        self.embed_url_base = "https://app.powerbi.com/reportEmbed"
        self.powerbi_api_base = "https://api.powerbi.com/v1.0/myorg"
        self.azure_tenant_id = settings.azure_tenant_id or ""
        self.azure_client_id = settings.azure_client_id or ""
        self.azure_client_secret = settings.azure_client_secret or ""
        self.access_token = None
        self.token_expiry = None
    
    def get_embed_token(self, report_id: str, dataset_id: str, user_email: str = None) -> Dict[str, Any]:
        """Generate Power BI embed token"""
        # In production, this would call Azure AD and Power BI REST API
        # For demo/simulation, we generate a mock token
        
        token_payload = {
            "ver": "0.2.0",
            "wcn": self.workspace_id,
            "wid": "stylehub-analytics",
            "rid": report_id,
            "did": dataset_id,
            "aud": "https://analysis.windows.net/powerbi/api",
            "iss": "PowerBIService",
            "nbf": int((datetime.utcnow() - timedelta(minutes=5)).timestamp()),
            "exp": int((datetime.utcnow() + timedelta(hours=1)).timestamp()),
            "wids": [self.workspace_id],
            "roles": [],
            "username": user_email or "admin@stylehub.com"
        }
        
        # Mock token generation (base64 encoded)
        token_json = json.dumps(token_payload)
        mock_token = base64.b64encode(token_json.encode()).decode()
        
        return {
            "token": f"eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.{mock_token}.mock_signature",
            "token_id": f"token-{report_id}-{int(datetime.utcnow().timestamp())}",
            "expiration": (datetime.utcnow() + timedelta(hours=1)).isoformat(),
            "type": "embed"
        }
    
    def get_dashboard_config(self, dashboard_id: str, user_email: str = None) -> Optional[Dict[str, Any]]:
        """Get dashboard configuration for embedding"""
        if dashboard_id not in self.dashboards:
            return None
        
        dashboard = self.dashboards[dashboard_id]
        
        # Generate embed token
        embed_token = self.get_embed_token(
            dashboard["report_id"],
            dashboard["dataset_id"],
            user_email
        )
        
        # Build embed URL
        embed_url = (
            f"{self.embed_url_base}?"
            f"reportId={dashboard['report_id']}&"
            f"groupId={self.workspace_id}&"
            f"w=2&"
            f"config=eyJjbHVzdGVyVXJsIjoiaHR0cHM6Ly9XQUJJLU5PUlRILU5PUlQtQVNJQS1yZWRpcmVjdC5hbmFseXNpcy53aW5kb3dzLm5ldCJ9"
        )
        
        return {
            "id": dashboard["id"],
            "name": dashboard["name"],
            "description": dashboard["description"],
            "icon": dashboard["icon"],
            "color": dashboard["color"],
            "report_id": dashboard["report_id"],
            "embed_url": embed_url,
            "embed_token": embed_token["token"],
            "token_expiration": embed_token["expiration"],
            "pages": dashboard["pages"],
            "default_page": dashboard["pages"][0] if dashboard["pages"] else None,
            "filters": dashboard["filters"]
        }
    
    def get_all_dashboards(self) -> List[Dict[str, Any]]:
        """Get list of all available dashboards"""
        return [
            {
                "id": key,
                "name": dash["name"],
                "description": dash["description"],
                "icon": dash["icon"],
                "color": dash["color"],
                "pages": dash["pages"]
            }
            for key, dash in self.dashboards.items()
        ]
    
    def get_dashboard_summary(self) -> Dict[str, Any]:
        """Get summary of all dashboards"""
        return {
            "total_dashboards": len(self.dashboards),
            "categories": {
                "sales": ["sales_analytics"],
                "forecasting": ["forecasting"],
                "security": ["anomaly_detection"],
                "customers": ["customer_insights"],
                "operations": ["inventory_analytics"],
                "ai": ["agent_analytics"]
            },
            "last_updated": datetime.utcnow().isoformat(),
            "power_bi_version": "2.0",
            "workspace": self.workspace_id
        }
    
    def refresh_dashboard_data(self, dashboard_id: str) -> Dict[str, Any]:
        """Trigger dashboard data refresh"""
        if dashboard_id not in self.dashboards:
            return {"error": "Dashboard not found"}
        
        dashboard = self.dashboards[dashboard_id]
        
        # Simulate refresh
        return {
            "dashboard_id": dashboard_id,
            "report_id": dashboard["report_id"],
            "dataset_id": dashboard["dataset_id"],
            "refresh_status": "started",
            "refresh_time": datetime.utcnow().isoformat(),
            "estimated_completion": (datetime.utcnow() + timedelta(minutes=5)).isoformat()
        }
    
    def export_dashboard(self, dashboard_id: str, format: str = "pdf") -> Dict[str, Any]:
        """Export dashboard to various formats"""
        if dashboard_id not in self.dashboards:
            return {"error": "Dashboard not found"}
        
        dashboard = self.dashboards[dashboard_id]
        
        supported_formats = ["pdf", "pptx", "xlsx", "csv"]
        
        if format not in supported_formats:
            return {"error": f"Format not supported. Use: {', '.join(supported_formats)}"}
        
        return {
            "dashboard_id": dashboard_id,
            "dashboard_name": dashboard["name"],
            "format": format,
            "export_url": f"/api/powerbi/export/{dashboard_id}.{format}",
            "status": "ready",
            "generated_at": datetime.utcnow().isoformat(),
            "expires_at": (datetime.utcnow() + timedelta(hours=24)).isoformat()
        }
    
    def get_dashboard_metrics(self, dashboard_id: str) -> Dict[str, Any]:
        """Get usage metrics for a dashboard"""
        if dashboard_id not in self.dashboards:
            return {"error": "Dashboard not found"}
        
        # Simulated metrics
        return {
            "dashboard_id": dashboard_id,
            "views_24h": 45,
            "views_7d": 189,
            "views_30d": 567,
            "unique_viewers": 23,
            "avg_session_duration_min": 12.5,
            "top_pages": [
                {"page": "Overview", "views": 234},
                {"page": "Trends", "views": 156},
                {"page": "Products", "views": 89}
            ],
            "last_viewed": (datetime.utcnow() - timedelta(hours=2)).isoformat()
        }
    
    def get_comprehensive_analytics(self) -> Dict[str, Any]:
        """Get comprehensive Power BI analytics configuration"""
        return {
            "dashboards": self.get_all_dashboards(),
            "summary": self.get_dashboard_summary(),
            "embed_config": {
                "type": "report",
                "settings": {
                    "filterPaneEnabled": True,
                    "navContentPaneEnabled": True,
                    "visiblePages": [],
                    "locale": "en-US"
                },
                "permissions": {
                    "read": True,
                    "write": False,
                    "create": False
                }
            },
            "features": {
                "real_time_refresh": True,
                "drill_through": True,
                "cross_report": True,
                "ai_insights": True,
                "smart_narratives": True,
                "decomposition_tree": True
            },
            "data_sources": [
                {
                    "name": "Azure SQL Database",
                    "type": "database",
                    "refresh_schedule": "Every 15 minutes"
                },
                {
                    "name": "Azure Data Lake",
                    "type": "storage",
                    "refresh_schedule": "Every hour"
                },
                {
                    "name": "Azure Synapse",
                    "type": "analytics",
                    "refresh_schedule": "Every 30 minutes"
                }
            ]
        }

    # ==================== Azure Power BI Integration ====================

    def get_azure_access_token(self) -> Optional[str]:
        """Get Azure AD access token for Power BI API"""
        if not all([self.azure_tenant_id, self.azure_client_id, self.azure_client_secret]):
            logger.warning("Azure AD credentials not configured")
            return None
        
        # Check if token is still valid
        if self.access_token and self.token_expiry and datetime.utcnow() < self.token_expiry:
            return self.access_token
        
        try:
            url = f"https://login.microsoftonline.com/{self.azure_tenant_id}/oauth2/v2.0/token"
            
            payload = {
                "grant_type": "client_credentials",
                "client_id": self.azure_client_id,
                "client_secret": self.azure_client_secret,
                "scope": "https://analysis.windows.net/powerbi/api/.default"
            }
            
            response = requests.post(url, data=payload, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            self.access_token = data.get("access_token")
            expires_in = data.get("expires_in", 3600)
            self.token_expiry = datetime.utcnow() + timedelta(seconds=expires_in - 300)  # 5 min buffer
            
            return self.access_token
            
        except Exception as e:
            logger.error(f"Failed to get Azure access token: {e}")
            return None

    def get_powerbi_headers(self) -> Dict[str, str]:
        """Get headers for Power BI API calls"""
        token = self.get_azure_access_token()
        if token:
            return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        return {"Content-Type": "application/json"}

    # ==================== Data Export for Power BI ====================

    def export_sales_data(self, db: Session, days: int = 90) -> List[Dict[str, Any]]:
        """Export sales data for Power BI dataset"""
        start_date = datetime.utcnow() - timedelta(days=days)
        
        orders = db.query(Order).filter(Order.created_at >= start_date).all()
        
        data = []
        for order in orders:
            for item in order.items:
                data.append({
                    "order_id": order.id,
                    "order_number": order.order_number,
                    "order_date": order.created_at.isoformat() if order.created_at else None,
                    "customer_id": order.user_id,
                    "customer_name": order.customer_name,
                    "product_id": item.product_id,
                    "product_name": item.product_name,
                    "category": db.query(Product.category).filter(Product.id == item.product_id).scalar() or "Unknown",
                    "quantity": item.quantity,
                    "unit_price": item.unit_price,
                    "total_amount": item.quantity * item.unit_price,
                    "order_total": order.total_amount,
                    "status": order.status,
                    "payment_method": order.payment_method,
                    "city": order.city,
                    "state": order.state
                })
        
        return data

    def export_customer_data(self, db: Session) -> List[Dict[str, Any]]:
        """Export customer data for Power BI dataset"""
        users = db.query(User).all()
        
        data = []
        for user in users:
            # Calculate customer metrics
            orders = db.query(Order).filter(Order.user_id == user.id).all()
            total_orders = len(orders)
            total_spent = sum(order.total_amount for order in orders)
            avg_order_value = total_spent / total_orders if total_orders > 0 else 0
            
            # Get last order date
            last_order = db.query(Order).filter(Order.user_id == user.id).order_by(Order.created_at.desc()).first()
            last_order_date = last_order.created_at.isoformat() if last_order else None
            
            # Get favorite category
            category_orders = db.query(Product.category, func.sum(OrderItem.quantity).label('qty'))\
                .join(OrderItem, Product.id == OrderItem.product_id)\
                .join(Order, OrderItem.order_id == Order.id)\
                .filter(Order.user_id == user.id)\
                .group_by(Product.category)\
                .order_by(func.sum(OrderItem.quantity).desc())\
                .first()
            
            favorite_category = category_orders[0] if category_orders else "N/A"
            
            data.append({
                "customer_id": user.id,
                "name": user.name,
                "email": user.email,
                "phone": user.phone,
                "registration_date": user.created_at.isoformat() if user.created_at else None,
                "total_orders": total_orders,
                "total_spent": round(total_spent, 2),
                "average_order_value": round(avg_order_value, 2),
                "last_order_date": last_order_date,
                "favorite_category": favorite_category,
                "is_admin": user.is_admin
            })
        
        return data

    def export_inventory_data(self, db: Session) -> List[Dict[str, Any]]:
        """Export inventory data for Power BI dataset"""
        products = db.query(Product).all()
        
        data = []
        for product in products:
            # Calculate sales velocity
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            units_sold = db.query(func.sum(OrderItem.quantity))\
                .join(Order, OrderItem.order_id == Order.id)\
                .filter(OrderItem.product_id == product.id, Order.created_at >= thirty_days_ago)\
                .scalar() or 0
            
            # Calculate days of inventory remaining
            daily_velocity = units_sold / 30 if units_sold > 0 else 0
            days_remaining = product.stock / daily_velocity if daily_velocity > 0 else float('inf')
            
            # Get revenue contribution
            total_revenue = db.query(func.sum(OrderItem.quantity * OrderItem.unit_price))\
                .filter(OrderItem.product_id == product.id)\
                .scalar() or 0
            
            data.append({
                "product_id": product.id,
                "sku": product.sku,
                "name": product.name,
                "category": product.category,
                "description": product.description,
                "price": product.price,
                "current_stock": product.stock,
                "units_sold_30d": int(units_sold),
                "daily_velocity": round(daily_velocity, 2),
                "days_of_inventory": round(days_remaining, 1) if days_remaining != float('inf') else 999,
                "total_revenue": round(total_revenue, 2),
                "stock_status": "Low" if product.stock < 10 else "Medium" if product.stock < 50 else "High",
                "created_at": product.created_at.isoformat() if product.created_at else None
            })
        
        return data

    def export_support_tickets_data(self, db: Session, days: int = 90) -> List[Dict[str, Any]]:
        """Export support tickets data for Power BI dataset"""
        start_date = datetime.utcnow() - timedelta(days=days)
        
        tickets = db.query(SupportTicket).filter(SupportTicket.created_at >= start_date).all()
        
        data = []
        for ticket in tickets:
            data.append({
                "ticket_id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
                "customer_email": ticket.customer_email,
                "subject": ticket.subject,
                "issue": ticket.issue,
                "status": ticket.status,
                "priority": ticket.priority,
                "source": ticket.source,
                "sentiment": ticket.sentiment,
                "order_number": ticket.order_number
            })
        
        return data

    def export_daily_metrics(self, db: Session, days: int = 30) -> List[Dict[str, Any]]:
        """Export daily aggregated metrics for Power BI dataset"""
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        data = []
        for i in range(days):
            date = start_date + timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            
            # Revenue
            revenue = db.query(func.sum(Order.total_amount)).filter(
                func.date(Order.created_at) == date.date()
            ).scalar() or 0
            
            # Orders
            orders_count = db.query(Order).filter(
                func.date(Order.created_at) == date.date()
            ).count()
            
            # New customers
            new_customers = db.query(User).filter(
                func.date(User.created_at) == date.date()
            ).count()
            
            # Support tickets
            tickets_count = db.query(SupportTicket).filter(
                func.date(SupportTicket.created_at) == date.date()
            ).count()
            
            # Average order value
            aov = revenue / orders_count if orders_count > 0 else 0
            
            data.append({
                "date": date_str,
                "revenue": round(revenue, 2),
                "orders_count": orders_count,
                "new_customers": new_customers,
                "support_tickets": tickets_count,
                "average_order_value": round(aov, 2),
                "day_of_week": date.strftime("%A"),
                "is_weekend": date.weekday() >= 5
            })
        
        return data

    def get_all_powerbi_datasets(self, db: Session) -> Dict[str, Any]:
        """Get all datasets formatted for Power BI import"""
        return {
            "sales_data": self.export_sales_data(db),
            "customer_data": self.export_customer_data(db),
            "inventory_data": self.export_inventory_data(db),
            "support_tickets": self.export_support_tickets_data(db),
            "daily_metrics": self.export_daily_metrics(db),
            "exported_at": datetime.utcnow().isoformat(),
            "schema_version": "1.0"
        }

    # ==================== Key Metrics for Dashboard ====================

    def get_key_metrics(self, db: Session) -> Dict[str, Any]:
        """Get key metrics for Power BI dashboard"""
        today = datetime.utcnow().date()
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
        # Revenue metrics
        total_revenue = db.query(func.sum(Order.total_amount)).scalar() or 0
        today_revenue = db.query(func.sum(Order.total_amount)).filter(
            func.date(Order.created_at) == today
        ).scalar() or 0
        month_revenue = db.query(func.sum(Order.total_amount)).filter(
            Order.created_at >= thirty_days_ago
        ).scalar() or 0
        
        # Order metrics
        total_orders = db.query(Order).count()
        today_orders = db.query(Order).filter(func.date(Order.created_at) == today).count()
        month_orders = db.query(Order).filter(Order.created_at >= thirty_days_ago).count()
        
        # Customer metrics
        total_customers = db.query(User).count()
        new_customers_month = db.query(User).filter(User.created_at >= thirty_days_ago).count()
        
        # Product metrics
        total_products = db.query(Product).count()
        low_stock_count = db.query(Product).filter(Product.stock < 10).count()
        
        # Support metrics
        open_tickets = db.query(SupportTicket).filter(SupportTicket.status == "Open").count()
        high_priority_tickets = db.query(SupportTicket).filter(
            SupportTicket.priority == "High",
            SupportTicket.status == "Open"
        ).count()
        
        # Calculate trends (compare to previous period)
        sixty_days_ago = datetime.utcnow() - timedelta(days=60)
        prev_month_revenue = db.query(func.sum(Order.total_amount)).filter(
            Order.created_at >= sixty_days_ago,
            Order.created_at < thirty_days_ago
        ).scalar() or 0
        
        revenue_trend = ((month_revenue - prev_month_revenue) / prev_month_revenue * 100) if prev_month_revenue > 0 else 0
        
        return {
            "revenue": {
                "total": round(total_revenue, 2),
                "today": round(today_revenue, 2),
                "this_month": round(month_revenue, 2),
                "trend_percent": round(revenue_trend, 1)
            },
            "orders": {
                "total": total_orders,
                "today": today_orders,
                "this_month": month_orders
            },
            "customers": {
                "total": total_customers,
                "new_this_month": new_customers_month
            },
            "products": {
                "total": total_products,
                "low_stock": low_stock_count
            },
            "support": {
                "open_tickets": open_tickets,
                "high_priority": high_priority_tickets
            },
            "updated_at": datetime.utcnow().isoformat()
        }

    def get_model_outputs(self, db: Session) -> Dict[str, Any]:
        """Get AI model outputs for Power BI dashboard"""
        # This integrates with other AI services
        from app.services.demand_forecasting_service import demand_forecasting_service
        from app.services.anomaly_detection_service import anomaly_detection_service
        from app.services.customer_segmentation_service import customer_segmentation_service
        
        try:
            # Get forecast
            forecast = demand_forecasting_service.forecast_revenue(db, days=30)
            
            # Get anomalies
            anomalies = anomaly_detection_service.detect_order_anomalies(db)
            
            # Get customer segments
            segments = customer_segmentation_service.segment_customers(db)
            
            return {
                "revenue_forecast": {
                    "next_30_days": sum(day.get("forecast", 0) for day in forecast.get("daily_forecasts", [])),
                    "confidence": forecast.get("confidence_intervals", {}).get("average", 0),
                    "trend": forecast.get("trend", "stable")
                },
                "anomalies": {
                    "count": len(anomalies.get("anomalies", [])),
                    "high_severity": len([a for a in anomalies.get("anomalies", []) if a.get("severity") == "high"]),
                    "latest": anomalies.get("anomalies", [])[:5]
                },
                "customer_segments": {
                    "segments": [
                        {"name": name, "count": data.get("count", 0), "percent": data.get("percentage", 0)}
                        for name, data in segments.get("segments", {}).items()
                    ],
                    "total_segmented": segments.get("total_customers", 0)
                }
            }
        except Exception as e:
            logger.error(f"Error getting model outputs: {e}")
            return {"error": str(e)}

    def get_anomaly_alerts_and_trends(self, db: Session) -> Dict[str, Any]:
        """Get anomaly alerts and trends for Power BI dashboard"""
        from app.services.anomaly_detection_service import anomaly_detection_service
        from app.services.admin_analytics_service import admin_analytics_service
        
        try:
            # Get order anomalies
            order_anomalies = anomaly_detection_service.detect_order_anomalies(db)
            
            # Get inventory anomalies
            inventory_anomalies = anomaly_detection_service.detect_inventory_anomalies(db)
            
            # Get admin anomaly alerts
            admin_alerts = admin_analytics_service.get_anomaly_alerts(db)
            
            # Get low stock alerts
            low_stock = admin_analytics_service.get_low_stock_alerts(db, threshold=10)
            
            # Calculate trends
            today = datetime.utcnow().date()
            yesterday = today - timedelta(days=1)
            
            today_revenue = db.query(func.sum(Order.total_amount)).filter(
                func.date(Order.created_at) == today
            ).scalar() or 0
            
            yesterday_revenue = db.query(func.sum(Order.total_amount)).filter(
                func.date(Order.created_at) == yesterday
            ).scalar() or 0
            
            revenue_change = ((today_revenue - yesterday_revenue) / yesterday_revenue * 100) if yesterday_revenue > 0 else 0
            
            return {
                "alerts": {
                    "order_anomalies": order_anomalies.get("anomalies", []),
                    "inventory_anomalies": inventory_anomalies.get("anomalies", []),
                    "admin_alerts": admin_alerts,
                    "low_stock": low_stock
                },
                "summary": {
                    "total_alerts": len(order_anomalies.get("anomalies", [])) + len(inventory_anomalies.get("anomalies", [])),
                    "high_priority": len([a for a in order_anomalies.get("anomalies", []) + inventory_anomalies.get("anomalies", []) 
                                        if a.get("severity") == "high"]),
                    "requires_action": len(low_stock) + len([a for a in admin_alerts if a.get("severity") == "high"])
                },
                "trends": {
                    "revenue_change_percent": round(revenue_change, 1),
                    "revenue_trend": "up" if revenue_change > 5 else "down" if revenue_change < -5 else "stable"
                }
            }
        except Exception as e:
            logger.error(f"Error getting anomaly alerts: {e}")
            return {"error": str(e)}

    def get_agent_driven_insights(self, db: Session) -> Dict[str, Any]:
        """Get AI agent-driven insights for Power BI dashboard"""
        from app.services.admin_analytics_service import admin_analytics_service
        from app.services.ai_multi_agent_service import ai_multi_agent_center
        
        try:
            # Get AI insights from admin analytics
            ai_insights = admin_analytics_service.get_ai_insights(db)
            
            # Get comprehensive dashboard data
            dashboard_data = admin_analytics_service.get_comprehensive_dashboard(db)
            
            return {
                "ai_insights": ai_insights,
                "top_selling_products": dashboard_data.get("top_selling_products", [])[:5],
                "inventory_trends": dashboard_data.get("inventory_trends", []),
                "order_status_breakdown": dashboard_data.get("order_status_breakdown", {}),
                "revenue_trends": dashboard_data.get("revenue_trends", [])[-7:],  # Last 7 days
                "customer_growth": dashboard_data.get("customer_growth", [])[-3:],  # Last 3 months
                "generated_at": datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"Error getting agent insights: {e}")
            return {"error": str(e)}


powerbi_service = PowerBIService()
