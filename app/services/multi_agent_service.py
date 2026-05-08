from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
from enum import Enum
import uuid

from app.models import Order, OrderItem, Product, SupportTicket, User


class AgentStatus(Enum):
    IDLE = "idle"
    ACTIVE = "active"
    BUSY = "busy"
    ERROR = "error"
    OFFLINE = "offline"


class AgentTask:
    def __init__(self, agent_name: str, task_type: str, params: Dict[str, Any]):
        self.id = str(uuid.uuid4())
        self.agent_name = agent_name
        self.task_type = task_type
        self.params = params
        self.status = "pending"
        self.result = None
        self.created_at = datetime.utcnow()
        self.completed_at = None
        self.error = None


class BaseAgent:
    """Base class for all agents"""
    
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.status = AgentStatus.IDLE
        self.last_activity = datetime.utcnow()
        self.tasks_completed = 0
        self.tasks_failed = 0
        self.health_score = 100
    
    def execute_task(self, task: AgentTask, db: Session) -> Dict[str, Any]:
        """Execute a task - to be overridden by subclasses"""
        raise NotImplementedError
    
    def get_status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "last_activity": self.last_activity.isoformat(),
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "health_score": self.health_score
        }


class InventoryAgent(BaseAgent):
    """AI-powered Inventory Management Agent"""
    
    def __init__(self):
        super().__init__("Inventory Agent", "Predicts shortages, recommends reorder quantities, detects inventory anomalies")
    
    def execute_task(self, task: AgentTask, db: Session) -> Dict[str, Any]:
        if task.task_type == "predict_shortages":
            return self.predict_shortages(db, task.params)
        elif task.task_type == "recommend_reorder":
            return self.recommend_reorder(db, task.params)
        elif task.task_type == "detect_anomalies":
            return self.detect_inventory_anomalies(db)
        elif task.task_type == "warehouse_analytics":
            return self.get_warehouse_analytics(db)
        else:
            return {"error": "Unknown task type"}
    
    def predict_shortages(self, db: Session, params: Dict[str, Any]) -> Dict[str, Any]:
        """Predict which products will run out of stock"""
        days_ahead = params.get("days_ahead", 14)
        threshold = params.get("threshold", 10)
        
        products = db.query(Product).all()
        predictions = []
        
        # Get last 30 days of sales data
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
        for product in products:
            # Calculate average daily sales
            sales = db.query(func.sum(OrderItem.quantity)).join(Order).filter(
                OrderItem.product_id == product.id,
                Order.created_at >= thirty_days_ago,
                Order.status.in_(['Delivered', 'Shipped'])
            ).scalar() or 0
            
            avg_daily_sales = sales / 30
            
            # Predict days until stockout
            if avg_daily_sales > 0:
                days_until_stockout = product.stock / avg_daily_sales
            else:
                days_until_stockout = float('inf')
            
            if days_until_stockout <= days_ahead and product.stock < threshold:
                predictions.append({
                    "product_id": product.id,
                    "name": product.name,
                    "current_stock": product.stock,
                    "avg_daily_sales": round(avg_daily_sales, 2),
                    "predicted_stockout_days": round(days_until_stockout, 1),
                    "urgency": "high" if days_until_stockout <= 7 else "medium"
                })
        
        return {
            "predictions": predictions,
            "total_at_risk": len(predictions),
            "generated_at": datetime.utcnow().isoformat()
        }
    
    def recommend_reorder(self, db: Session, params: Dict[str, Any]) -> Dict[str, Any]:
        """Recommend reorder quantities based on demand forecasting"""
        product_id = params.get("product_id")
        lead_time_days = params.get("lead_time_days", 7)
        safety_stock_days = params.get("safety_stock_days", 7)
        
        if product_id:
            product = db.query(Product).filter(Product.id == product_id).first()
            if not product:
                return {"error": "Product not found"}
            products = [product]
        else:
            products = db.query(Product).all()
        
        recommendations = []
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
        for product in products:
            # Calculate demand during lead time
            sales = db.query(func.sum(OrderItem.quantity)).join(Order).filter(
                OrderItem.product_id == product.id,
                Order.created_at >= thirty_days_ago,
                Order.status.in_(['Delivered', 'Shipped'])
            ).scalar() or 0
            
            avg_daily_demand = sales / 30
            lead_time_demand = avg_daily_demand * lead_time_days
            safety_stock = avg_daily_demand * safety_stock_days
            
            reorder_point = lead_time_demand + safety_stock
            reorder_quantity = max(0, reorder_point - product.stock)
            
            if reorder_quantity > 0 or product.stock < reorder_point * 0.5:
                recommendations.append({
                    "product_id": product.id,
                    "name": product.name,
                    "current_stock": product.stock,
                    "reorder_point": round(reorder_point, 0),
                    "recommended_quantity": round(max(reorder_quantity, avg_daily_demand * 30), 0),
                    "lead_time_demand": round(lead_time_demand, 2),
                    "safety_stock": round(safety_stock, 2),
                    "priority": "high" if product.stock < safety_stock else "medium"
                })
        
        return {
            "recommendations": recommendations,
            "total_recommendations": len(recommendations),
            "parameters": {
                "lead_time_days": lead_time_days,
                "safety_stock_days": safety_stock_days
            },
            "generated_at": datetime.utcnow().isoformat()
        }
    
    def detect_inventory_anomalies(self, db: Session) -> Dict[str, Any]:
        """Detect unusual inventory patterns"""
        from sqlalchemy import func
        
        anomalies = []
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
        # Products with sudden demand spikes
        products = db.query(Product).all()
        
        for product in products:
            # Get daily sales for last 30 days
            daily_sales = db.query(
                func.date(Order.created_at).label('date'),
                func.sum(OrderItem.quantity).label('quantity')
            ).join(OrderItem).filter(
                OrderItem.product_id == product.id,
                Order.created_at >= thirty_days_ago,
                Order.status.in_(['Delivered', 'Shipped'])
            ).group_by(func.date(Order.created_at)).all()
            
            if len(daily_sales) >= 7:
                quantities = [s.quantity for s in daily_sales]
                avg_quantity = sum(quantities) / len(quantities)
                
                # Check for recent spike
                recent_avg = sum(quantities[-7:]) / 7
                if recent_avg > avg_quantity * 3 and product.stock < recent_avg * 7:
                    anomalies.append({
                        "type": "demand_spike",
                        "product_id": product.id,
                        "name": product.name,
                        "current_stock": product.stock,
                        "recent_avg_daily_sales": round(recent_avg, 2),
                        "overall_avg_daily_sales": round(avg_quantity, 2),
                        "severity": "high"
                    })
        
        # Products with no sales but high stock
        all_products = db.query(Product).filter(Product.stock > 50).all()
        for product in all_products:
            recent_sales = db.query(func.sum(OrderItem.quantity)).join(Order).filter(
                OrderItem.product_id == product.id,
                Order.created_at >= thirty_days_ago
            ).scalar() or 0
            
            if recent_sales == 0:
                anomalies.append({
                    "type": "dead_stock",
                    "product_id": product.id,
                    "name": product.name,
                    "current_stock": product.stock,
                    "last_30_days_sales": 0,
                    "severity": "medium"
                })
        
        return {
            "anomalies": anomalies,
            "total_anomalies": len(anomalies),
            "generated_at": datetime.utcnow().isoformat()
        }
    
    def get_warehouse_analytics(self, db: Session) -> Dict[str, Any]:
        """Get comprehensive warehouse analytics"""
        # Total inventory value
        total_value = db.query(func.sum(Product.price * Product.stock)).scalar() or 0
        
        # Stock by category
        category_data = db.query(
            Product.category,
            func.sum(Product.stock).label('total_stock'),
            func.sum(Product.price * Product.stock).label('total_value'),
            func.count(Product.id).label('product_count')
        ).group_by(Product.category).all()
        
        # Low stock items
        low_stock = db.query(Product).filter(Product.stock < 10).count()
        
        # Out of stock items
        out_of_stock = db.query(Product).filter(Product.stock == 0).count()
        
        return {
            "total_inventory_value": round(total_value, 2),
            "total_products": db.query(Product).count(),
            "low_stock_count": low_stock,
            "out_of_stock_count": out_of_stock,
            "categories": [
                {
                    "category": cat.category,
                    "total_stock": cat.total_stock,
                    "total_value": round(cat.total_value, 2),
                    "product_count": cat.product_count
                }
                for cat in category_data
            ],
            "generated_at": datetime.utcnow().isoformat()
        }


class RetailAnalystAgent(BaseAgent):
    """AI-powered Retail Analysis Agent"""
    
    def __init__(self):
        super().__init__("Retail Analyst Agent", "Analyzes sales trends, customer behavior, and market patterns")
    
    def execute_task(self, task: AgentTask, db: Session) -> Dict[str, Any]:
        if task.task_type == "sales_trend_analysis":
            return self.analyze_sales_trends(db, task.params)
        elif task.task_type == "customer_segmentation":
            return self.analyze_customer_segments(db)
        elif task.task_type == "product_performance":
            return self.analyze_product_performance(db)
        else:
            return {"error": "Unknown task type"}
    
    def analyze_sales_trends(self, db: Session, params: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze sales trends and patterns"""
        days = params.get("days", 30)
        start_date = datetime.utcnow() - timedelta(days=days)
        
        # Daily sales
        daily_sales = db.query(
            func.date(Order.created_at).label('date'),
            func.sum(Order.total_amount).label('revenue'),
            func.count(Order.id).label('orders')
        ).filter(
            Order.created_at >= start_date,
            Order.status.in_(['Delivered', 'Shipped'])
        ).group_by(func.date(Order.created_at)).all()
        
        # Category performance
        category_sales = db.query(
            Product.category,
            func.sum(OrderItem.quantity).label('units_sold'),
            func.sum(OrderItem.quantity * OrderItem.unit_price).label('revenue')
        ).join(OrderItem).join(Order).filter(
            Order.created_at >= start_date,
            Order.status.in_(['Delivered', 'Shipped'])
        ).group_by(Product.category).all()
        
        # Peak hours
        hourly_sales = db.query(
            func.hour(Order.created_at).label('hour'),
            func.sum(Order.total_amount).label('revenue')
        ).filter(
            Order.created_at >= start_date,
            Order.status.in_(['Delivered', 'Shipped'])
        ).group_by(func.hour(Order.created_at)).all()
        
        return {
            "period": f"Last {days} days",
            "daily_trends": [
                {"date": str(s.date), "revenue": float(s.revenue), "orders": s.orders}
                for s in daily_sales
            ],
            "category_performance": [
                {"category": c.category, "units_sold": c.units_sold, "revenue": float(c.revenue)}
                for c in category_sales
            ],
            "peak_hours": [
                {"hour": h.hour, "revenue": float(h.revenue)}
                for h in hourly_sales
            ],
            "generated_at": datetime.utcnow().isoformat()
        }
    
    def analyze_customer_segments(self, db: Session) -> Dict[str, Any]:
        """Analyze customer segmentation"""
        from app.services.customer_segmentation_service import customer_segmentation_service
        
        segments = customer_segmentation_service.get_all_customer_segments(db)
        
        # Add segment insights
        insights = []
        for segment, count in segments.items():
            if count > 0:
                insights.append({
                    "segment": segment,
                    "count": count,
                    "recommendations": customer_segmentation_service.get_segment_recommendations(segment)
                })
        
        return {
            "segments": segments,
            "insights": insights,
            "total_customers": sum(segments.values()),
            "generated_at": datetime.utcnow().isoformat()
        }
    
    def analyze_product_performance(self, db: Session) -> Dict[str, Any]:
        """Analyze product performance metrics"""
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
        # Top performers
        top_products = db.query(
            Product.id,
            Product.name,
            Product.category,
            func.sum(OrderItem.quantity).label('units_sold'),
            func.sum(OrderItem.quantity * OrderItem.unit_price).label('revenue'),
            Product.stock
        ).join(OrderItem).join(Order).filter(
            Order.created_at >= thirty_days_ago,
            Order.status.in_(['Delivered', 'Shipped'])
        ).group_by(Product.id).order_by(func.sum(OrderItem.quantity).desc()).limit(10).all()
        
        # Underperformers (high stock, low sales)
        all_products = db.query(Product).filter(Product.stock > 20).all()
        underperformers = []
        
        for product in all_products:
            recent_sales = db.query(func.sum(OrderItem.quantity)).join(Order).filter(
                OrderItem.product_id == product.id,
                Order.created_at >= thirty_days_ago,
                Order.status.in_(['Delivered', 'Shipped'])
            ).scalar() or 0
            
            if recent_sales < 5 and product.stock > 50:
                underperformers.append({
                    "product_id": product.id,
                    "name": product.name,
                    "stock": product.stock,
                    "monthly_sales": recent_sales,
                    "turnover_rate": round(recent_sales / product.stock, 3) if product.stock > 0 else 0
                })
        
        return {
            "top_performers": [
                {
                    "product_id": p.id,
                    "name": p.name,
                    "category": p.category,
                    "units_sold": p.units_sold,
                    "revenue": float(p.revenue),
                    "stock": p.stock
                }
                for p in top_products
            ],
            "underperformers": underperformers[:10],
            "generated_at": datetime.utcnow().isoformat()
        }


class MLInsightsAgent(BaseAgent):
    """AI-powered ML Insights Agent"""
    
    def __init__(self):
        super().__init__("ML Insights Agent", "Provides AI-driven insights and predictions")
    
    def execute_task(self, task: AgentTask, db: Session) -> Dict[str, Any]:
        if task.task_type == "revenue_prediction":
            return self.predict_revenue(db, task.params)
        elif task.task_type == "churn_prediction":
            return self.predict_churn(db)
        elif task.task_type == "demand_forecast":
            return self.forecast_demand(db, task.params)
        else:
            return {"error": "Unknown task type"}
    
    def predict_revenue(self, db: Session, params: Dict[str, Any]) -> Dict[str, Any]:
        """Predict future revenue"""
        days = params.get("days", 30)
        
        # Get historical revenue
        historical = db.query(
            func.sum(Order.total_amount)
        ).filter(
            Order.created_at >= datetime.utcnow() - timedelta(days=30),
            Order.status.in_(['Delivered', 'Shipped'])
        ).scalar() or 0
        
        avg_daily = historical / 30 if historical > 0 else 5000
        
        # Simple trend-based prediction
        predicted_revenue = avg_daily * days
        
        return {
            "predicted_revenue": round(predicted_revenue, 2),
            "confidence": "medium",
            "avg_daily_revenue": round(avg_daily, 2),
            "prediction_days": days,
            "generated_at": datetime.utcnow().isoformat()
        }
    
    def predict_churn(self, db: Session) -> Dict[str, Any]:
        """Predict customer churn risk"""
        sixty_days_ago = datetime.utcnow() - timedelta(days=60)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
        # Get all users
        users = db.query(User).all()
        
        at_risk = []
        for user in users:
            # Last order date
            last_order = db.query(Order).filter(
                Order.user_id == user.id
            ).order_by(Order.created_at.desc()).first()
            
            if last_order:
                days_since_last_order = (datetime.utcnow() - last_order.created_at).days
                
                # Calculate risk score
                risk_score = 0
                if days_since_last_order > 60:
                    risk_score += 50
                if days_since_last_order > 30:
                    risk_score += 30
                
                # Order frequency check
                total_orders = db.query(Order).filter(
                    Order.user_id == user.id,
                    Order.created_at >= sixty_days_ago
                ).count()
                
                if total_orders == 0 and days_since_last_order > 30:
                    risk_score += 20
                
                if risk_score > 50:
                    at_risk.append({
                        "user_id": user.id,
                        "email": user.email,
                        "risk_score": risk_score,
                        "days_since_last_order": days_since_last_order,
                        "last_order_date": last_order.created_at.isoformat()
                    })
        
        return {
            "at_risk_customers": at_risk,
            "total_at_risk": len(at_risk),
            "generated_at": datetime.utcnow().isoformat()
        }
    
    def forecast_demand(self, db: Session, params: Dict[str, Any]) -> Dict[str, Any]:
        """Forecast product demand"""
        from app.services.demand_forecasting_service import demand_forecasting_service
        
        return demand_forecasting_service.train_and_forecast(db, periods=params.get("days", 30))


class DocumentIntelligenceAgent(BaseAgent):
    """AI-powered Document Intelligence Agent"""
    
    def __init__(self):
        super().__init__("Document Intelligence Agent", "Analyzes documents, extracts insights from PDFs and manuals")
    
    def execute_task(self, task: AgentTask, db: Session) -> Dict[str, Any]:
        if task.task_type == "analyze_documents":
            return self.analyze_documents(db)
        elif task.task_type == "extract_keywords":
            return self.extract_keywords(task.params)
        elif task.task_type == "summarize_content":
            return self.summarize_content(task.params)
        else:
            return {"error": "Unknown task type"}
    
    def analyze_documents(self, db: Session) -> Dict[str, Any]:
        """Analyze indexed documents"""
        from app.services.document_search_service import user_document_search_service
        
        try:
            documents = user_document_search_service.list_documents()
            
            return {
                "total_documents": len(documents),
                "documents": documents,
                "generated_at": datetime.utcnow().isoformat()
            }
        except:
            return {
                "total_documents": 0,
                "documents": [],
                "message": "Document search service not available"
            }
    
    def extract_keywords(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Extract keywords from text"""
        text = params.get("text", "")
        
        # Simple keyword extraction
        import re
        words = re.findall(r'\b[A-Za-z]{4,}\b', text.lower())
        word_counts = {}
        for word in words:
            word_counts[word] = word_counts.get(word, 0) + 1
        
        top_keywords = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:20]
        
        return {
            "keywords": [{"word": word, "count": count} for word, count in top_keywords],
            "total_words": len(words),
            "unique_words": len(word_counts)
        }
    
    def summarize_content(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Summarize document content"""
        # Placeholder for summarization
        return {
            "summary": "Document summarization requires additional NLP setup",
            "status": "placeholder"
        }


class MultiAgentControlCenter:
    """Central orchestration hub for all agents"""
    
    def __init__(self):
        self.agents: Dict[str, BaseAgent] = {
            "inventory": InventoryAgent(),
            "retail_analyst": RetailAnalystAgent(),
            "ml_insights": MLInsightsAgent(),
            "document_intelligence": DocumentIntelligenceAgent()
        }
        self.task_queue: List[AgentTask] = []
        self.orchestration_logs: List[Dict[str, Any]] = []
    
    def get_agent_status(self) -> Dict[str, Any]:
        """Get status of all agents"""
        return {
            "agents": {name: agent.get_status() for name, agent in self.agents.items()},
            "total_agents": len(self.agents),
            "active_agents": sum(1 for a in self.agents.values() if a.status == AgentStatus.ACTIVE),
            "queue_length": len(self.task_queue)
        }
    
    def execute_task(self, agent_name: str, task_type: str, params: Dict[str, Any], db: Session) -> Dict[str, Any]:
        """Execute a task through a specific agent"""
        if agent_name not in self.agents:
            return {"error": f"Agent {agent_name} not found"}
        
        agent = self.agents[agent_name]
        task = AgentTask(agent_name, task_type, params)
        
        # Update agent status
        agent.status = AgentStatus.BUSY
        agent.last_activity = datetime.utcnow()
        
        try:
            result = agent.execute_task(task, db)
            task.result = result
            task.status = "completed"
            task.completed_at = datetime.utcnow()
            agent.tasks_completed += 1
            agent.status = AgentStatus.ACTIVE
        except Exception as e:
            task.error = str(e)
            task.status = "failed"
            agent.tasks_failed += 1
            agent.status = AgentStatus.ERROR
            agent.health_score = max(0, agent.health_score - 10)
        
        self.task_queue.append(task)
        
        # Log orchestration
        self.orchestration_logs.append({
            "timestamp": datetime.utcnow().isoformat(),
            "agent": agent_name,
            "task": task_type,
            "status": task.status,
            "task_id": task.id
        })
        
        return {
            "task_id": task.id,
            "status": task.status,
            "result": task.result,
            "error": task.error
        }
    
    def get_task_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent task execution history"""
        tasks = sorted(self.task_queue, key=lambda t: t.created_at, reverse=True)[:limit]
        
        return [
            {
                "id": t.id,
                "agent": t.agent_name,
                "type": t.task_type,
                "status": t.status,
                "created_at": t.created_at.isoformat(),
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                "has_result": t.result is not None
            }
            for t in tasks
        ]
    
    def get_orchestration_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get orchestration logs"""
        return sorted(self.orchestration_logs, key=lambda x: x["timestamp"], reverse=True)[:limit]
    
    def reset_agent(self, agent_name: str) -> bool:
        """Reset an agent to idle state"""
        if agent_name in self.agents:
            self.agents[agent_name].status = AgentStatus.IDLE
            self.agents[agent_name].health_score = 100
            return True
        return False


# Global control center instance
multi_agent_center = MultiAgentControlCenter()
