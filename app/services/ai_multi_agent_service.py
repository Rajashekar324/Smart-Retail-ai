"""AI-Powered Multi-Agent System with LLM Integration, RAG, and Orchestration"""
from __future__ import annotations

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Callable
from enum import Enum
from dataclasses import dataclass, field
from sqlalchemy.orm import Session
from sqlalchemy import func
import uuid

from app.models import Order, OrderItem, Product, SupportTicket, User

# Import LLM service
try:
    from app.services.llm_service import llm_service, vectorstore, LLMService
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False
    logging.warning("LLM service not available")

# Configure logging
logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    IDLE = "idle"
    ACTIVE = "active"
    BUSY = "busy"
    ERROR = "error"
    OFFLINE = "offline"


@dataclass
class AgentMessage:
    """Message for inter-agent communication (MCP-like protocol)"""
    from_agent: str
    to_agent: str
    message_type: str  # "query", "response", "task", "broadcast"
    content: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class AgentTask:
    """Task for agents to execute"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_name: str = ""
    task_type: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending, running, completed, failed
    result: Any = None
    error: str = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime = None
    rag_context: str = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "agent_name": self.agent_name,
            "task_type": self.task_type,
            "params": self.params,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "rag_enhanced": self.rag_context is not None
        }


class BaseAIAgent:
    """Base class for AI-powered agents"""
    
    def __init__(self, name: str, description: str, system_prompt: str):
        self.name = name
        self.description = description
        self.system_prompt = system_prompt
        self.status = AgentStatus.IDLE
        self.last_activity = datetime.utcnow()
        self.tasks_completed = 0
        self.tasks_failed = 0
        self.health_score = 100
        self.llm_service = llm_service if AI_AVAILABLE else None
        self.message_queue: List[AgentMessage] = []
        self.knowledge_base: List[str] = []
    
    def get_status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "last_activity": self.last_activity.isoformat(),
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "health_score": self.health_score,
            "ai_available": self.llm_service is not None and self.llm_service.is_available(),
            "pending_messages": len(self.message_queue)
        }
    
    def execute_task(self, task: AgentTask, db: Session) -> Dict[str, Any]:
        """Execute task - to be overridden by subclasses"""
        raise NotImplementedError
    
    def send_message(self, to_agent: str, message_type: str, content: Dict[str, Any]) -> AgentMessage:
        """Send message to another agent (MCP protocol)"""
        message = AgentMessage(
            from_agent=self.name,
            to_agent=to_agent,
            message_type=message_type,
            content=content
        )
        return message
    
    def receive_message(self, message: AgentMessage) -> None:
        """Receive message from another agent"""
        self.message_queue.append(message)
        logger.info(f"{self.name} received message from {message.from_agent}: {message.message_type}")
    
    def process_messages(self) -> List[Dict[str, Any]]:
        """Process pending messages"""
        processed = []
        for msg in self.message_queue:
            processed.append({
                "from": msg.from_agent,
                "type": msg.message_type,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat()
            })
        self.message_queue.clear()
        return processed
    
    def enhance_with_rag(self, query: str, task: AgentTask) -> str:
        """Enhance task with RAG context"""
        if self.llm_service and self.llm_service.vectorstore:
            context = self.llm_service.vectorstore.get_relevant_context(query, k=3)
            task.rag_context = context
            return context
        return ""
    
    def analyze_with_llm(self, data: Dict[str, Any], question: str = None) -> Dict[str, Any]:
        """Analyze data using LLM"""
        if not self.llm_service or not self.llm_service.is_available():
            return {
                "success": False,
                "error": "LLM service not available",
                "insights": "AI analysis unavailable - using rule-based fallback"
            }
        
        analysis_type = self.name.replace(" Agent", "").lower()
        return self.llm_service.analyze_data_with_llm(data, analysis_type, question)


class AIInventoryAgent(BaseAIAgent):
    """AI-powered Inventory Management Agent with LLM insights"""
    
    def __init__(self):
        super().__init__(
            name="Inventory Agent",
            description="AI-powered inventory management with predictive analytics",
            system_prompt="""You are an expert Inventory Management AI Agent.
Your role is to analyze inventory data, predict shortages, recommend reorder quantities,
and detect anomalies using both statistical methods and AI insights.

When analyzing data:
1. Identify critical stock levels and urgent reorder needs
2. Predict demand patterns using historical data
3. Detect anomalies in inventory movements
4. Provide actionable recommendations with priority levels
5. Consider seasonal trends and lead times

Always provide quantitative insights with specific numbers and confidence levels."""
        )
    
    def execute_task(self, task: AgentTask, db: Session) -> Dict[str, Any]:
        task_handlers = {
            "predict_shortages": self.predict_shortages,
            "recommend_reorder": self.recommend_reorder,
            "detect_anomalies": self.detect_inventory_anomalies,
            "warehouse_analytics": self.get_warehouse_analytics,
            "ai_inventory_analysis": self.ai_inventory_analysis
        }
        
        handler = task_handlers.get(task.task_type)
        if handler:
            return handler(db, task.params, task)
        return {"error": f"Unknown task type: {task.task_type}"}
    
    def predict_shortages(self, db: Session, params: Dict[str, Any], task: AgentTask) -> Dict[str, Any]:
        """Predict inventory shortages with AI insights"""
        days_ahead = params.get("days_ahead", 14)
        threshold = params.get("threshold", 10)
        
        # Get data from database
        products = db.query(Product).all()
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
        predictions = []
        for product in products:
            sales = db.query(func.sum(OrderItem.quantity)).join(Order).filter(
                OrderItem.product_id == product.id,
                Order.created_at >= thirty_days_ago,
                Order.status.in_(['Delivered', 'Shipped'])
            ).scalar() or 0
            
            avg_daily_sales = sales / 30
            days_until_stockout = product.stock / avg_daily_sales if avg_daily_sales > 0 else float('inf')
            
            if days_until_stockout <= days_ahead and product.stock < threshold:
                predictions.append({
                    "product_id": product.id,
                    "name": product.name,
                    "current_stock": product.stock,
                    "avg_daily_sales": round(avg_daily_sales, 2),
                    "predicted_stockout_days": round(days_until_stockout, 1),
                    "urgency": "high" if days_until_stockout <= 7 else "medium"
                })
        
        # Get AI insights
        if predictions and self.llm_service and self.llm_service.is_available():
            ai_result = self.analyze_with_llm(
                {"predictions": predictions, "days_ahead": days_ahead},
                "Analyze these shortage predictions and provide strategic recommendations"
            )
            ai_insights = ai_result.get("response", "AI analysis unavailable")
        else:
            ai_insights = "No critical shortages detected or AI unavailable"
        
        return {
            "predictions": predictions,
            "total_at_risk": len(predictions),
            "ai_insights": ai_insights,
            "generated_at": datetime.utcnow().isoformat()
        }
    
    def recommend_reorder(self, db: Session, params: Dict[str, Any], task: AgentTask) -> Dict[str, Any]:
        """AI-powered reorder recommendations"""
        product_id = params.get("product_id")
        lead_time_days = params.get("lead_time_days", 7)
        safety_stock_days = params.get("safety_stock_days", 7)
        
        if product_id:
            product = db.query(Product).filter(Product.id == product_id).first()
            products = [product] if product else []
        else:
            products = db.query(Product).all()
        
        recommendations = []
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
        for product in products:
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
        
        # AI analysis
        if recommendations and self.llm_service and self.llm_service.is_available():
            ai_result = self.analyze_with_llm(
                {"recommendations": recommendations},
                "Analyze these reorder recommendations and optimize the ordering strategy"
            )
            ai_strategy = ai_result.get("response", "AI analysis unavailable")
        else:
            ai_strategy = "No reorder recommendations needed or AI unavailable"
        
        return {
            "recommendations": recommendations,
            "total_recommendations": len(recommendations),
            "ai_strategy": ai_strategy,
            "parameters": {"lead_time_days": lead_time_days, "safety_stock_days": safety_stock_days},
            "generated_at": datetime.utcnow().isoformat()
        }
    
    def detect_inventory_anomalies(self, db: Session, params: Dict[str, Any], task: AgentTask) -> Dict[str, Any]:
        """Detect inventory anomalies with AI"""
        anomalies = []
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
        products = db.query(Product).all()
        
        for product in products:
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
        
        # AI anomaly analysis
        if anomalies and self.llm_service and self.llm_service.is_available():
            ai_result = self.analyze_with_llm(
                {"anomalies": anomalies},
                "Analyze these inventory anomalies and provide root cause analysis"
            )
            ai_analysis = ai_result.get("response", "AI analysis unavailable")
        else:
            ai_analysis = "No anomalies detected or AI unavailable"
        
        return {
            "anomalies": anomalies,
            "total_anomalies": len(anomalies),
            "ai_analysis": ai_analysis,
            "generated_at": datetime.utcnow().isoformat()
        }
    
    def get_warehouse_analytics(self, db: Session, params: Dict[str, Any], task: AgentTask) -> Dict[str, Any]:
        """Comprehensive warehouse analytics"""
        total_value = db.query(func.sum(Product.price * Product.stock)).scalar() or 0
        
        category_data = db.query(
            Product.category,
            func.sum(Product.stock).label('total_stock'),
            func.sum(Product.price * Product.stock).label('total_value'),
            func.count(Product.id).label('product_count')
        ).group_by(Product.category).all()
        
        low_stock = db.query(Product).filter(Product.stock < 10).count()
        out_of_stock = db.query(Product).filter(Product.stock == 0).count()
        
        analytics_data = {
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
            ]
        }
        
        # AI insights
        if self.llm_service and self.llm_service.is_available():
            ai_result = self.analyze_with_llm(
                analytics_data,
                "Analyze warehouse analytics and provide optimization recommendations"
            )
            ai_insights = ai_result.get("response", "AI analysis unavailable")
        else:
            ai_insights = "AI insights unavailable"
        
        analytics_data["ai_insights"] = ai_insights
        analytics_data["generated_at"] = datetime.utcnow().isoformat()
        
        return analytics_data
    
    def ai_inventory_analysis(self, db: Session, params: Dict[str, Any], task: AgentTask) -> Dict[str, Any]:
        """Pure AI-driven inventory analysis"""
        # Gather comprehensive inventory data
        total_products = db.query(Product).count()
        low_stock = db.query(Product).filter(Product.stock < 10).count()
        out_of_stock = db.query(Product).filter(Product.stock == 0).count()
        total_value = db.query(func.sum(Product.price * Product.stock)).scalar() or 0
        
        data = {
            "total_products": total_products,
            "low_stock": low_stock,
            "out_of_stock": out_of_stock,
            "total_inventory_value": total_value,
            "analysis_date": datetime.utcnow().isoformat()
        }
        
        # Enhance with RAG
        context = self.enhance_with_rag("inventory optimization best practices", task)
        
        # Generate AI analysis
        if self.llm_service and self.llm_service.is_available():
            result = self.llm_service.generate_with_rag(
                query=f"Analyze inventory status: {json.dumps(data)}",
                system_prompt=self.system_prompt,
                k=3
            )
            
            return {
                "analysis": result.get("response", "Analysis unavailable"),
                "rag_enhanced": result.get("rag_used", False),
                "model_used": result.get("model", "unknown"),
                "data": data
            }
        
        return {"error": "LLM service not available", "data": data}


class AIRetailAnalystAgent(BaseAIAgent):
    """AI-powered Retail Analysis Agent"""
    
    def __init__(self):
        super().__init__(
            name="Retail Analyst Agent",
            description="AI-powered retail analysis with trend detection and customer insights",
            system_prompt="""You are an expert Retail Analytics AI Agent.
Your role is to analyze sales trends, customer behavior, product performance, and market patterns.

When analyzing retail data:
1. Identify sales trends and seasonality
2. Segment customers and analyze behavior
3. Evaluate product performance and category trends
4. Detect peak hours and buying patterns
5. Provide actionable business recommendations

Always support insights with data and provide confidence levels."""
        )
    
    def execute_task(self, task: AgentTask, db: Session) -> Dict[str, Any]:
        task_handlers = {
            "sales_trend_analysis": self.analyze_sales_trends,
            "customer_segmentation": self.analyze_customer_segments,
            "product_performance": self.analyze_product_performance,
            "ai_retail_insights": self.ai_retail_insights
        }
        
        handler = task_handlers.get(task.task_type)
        if handler:
            return handler(db, task.params, task)
        return {"error": f"Unknown task type: {task.task_type}"}
    
    def analyze_sales_trends(self, db: Session, params: Dict[str, Any], task: AgentTask) -> Dict[str, Any]:
        """Analyze sales trends with AI insights"""
        days = params.get("days", 30)
        start_date = datetime.utcnow() - timedelta(days=days)
        
        # Gather data
        daily_sales = db.query(
            func.date(Order.created_at).label('date'),
            func.sum(Order.total_amount).label('revenue'),
            func.count(Order.id).label('orders')
        ).filter(
            Order.created_at >= start_date,
            Order.status.in_(['Delivered', 'Shipped'])
        ).group_by(func.date(Order.created_at)).all()
        
        category_sales = db.query(
            Product.category,
            func.sum(OrderItem.quantity).label('units_sold'),
            func.sum(OrderItem.quantity * OrderItem.unit_price).label('revenue')
        ).join(OrderItem).join(Order).filter(
            Order.created_at >= start_date,
            Order.status.in_(['Delivered', 'Shipped'])
        ).group_by(Product.category).all()
        
        data = {
            "period": f"Last {days} days",
            "daily_trends": [{"date": str(s.date), "revenue": float(s.revenue), "orders": s.orders} for s in daily_sales],
            "category_performance": [{"category": c.category, "units_sold": c.units_sold, "revenue": float(c.revenue)} for c in category_sales]
        }
        
        # AI analysis
        if self.llm_service and self.llm_service.is_available():
            ai_result = self.analyze_with_llm(data, "Analyze sales trends and identify patterns")
            ai_insights = ai_result.get("response", "AI analysis unavailable")
        else:
            ai_insights = "AI insights unavailable"
        
        data["ai_insights"] = ai_insights
        data["generated_at"] = datetime.utcnow().isoformat()
        
        return data
    
    def analyze_customer_segments(self, db: Session, params: Dict[str, Any], task: AgentTask) -> Dict[str, Any]:
        """AI-powered customer segmentation"""
        try:
            from app.services.customer_segmentation_service import customer_segmentation_service
            segments = customer_segmentation_service.get_all_customer_segments(db)
            
            insights = []
            for segment, count in segments.items():
                if count > 0:
                    insights.append({
                        "segment": segment,
                        "count": count,
                        "recommendations": customer_segmentation_service.get_segment_recommendations(segment)
                    })
            
            data = {
                "segments": segments,
                "insights": insights,
                "total_customers": sum(segments.values())
            }
            
            # AI analysis
            if self.llm_service and self.llm_service.is_available():
                ai_result = self.analyze_with_llm(data, "Analyze customer segments and provide targeted strategies")
                ai_strategy = ai_result.get("response", "AI analysis unavailable")
            else:
                ai_strategy = "AI insights unavailable"
            
            data["ai_strategy"] = ai_strategy
            data["generated_at"] = datetime.utcnow().isoformat()
            
            return data
        except Exception as e:
            return {"error": str(e)}
    
    def analyze_product_performance(self, db: Session, params: Dict[str, Any], task: AgentTask) -> Dict[str, Any]:
        """Analyze product performance with AI"""
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
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
        
        data = {
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
            ]
        }
        
        # AI analysis
        if self.llm_service and self.llm_service.is_available():
            ai_result = self.analyze_with_llm(data, "Analyze product performance and identify opportunities")
            ai_insights = ai_result.get("response", "AI analysis unavailable")
        else:
            ai_insights = "AI insights unavailable"
        
        data["ai_insights"] = ai_insights
        data["generated_at"] = datetime.utcnow().isoformat()
        
        return data
    
    def ai_retail_insights(self, db: Session, params: Dict[str, Any], task: AgentTask) -> Dict[str, Any]:
        """Generate comprehensive AI retail insights"""
        # Enhance with RAG
        context = self.enhance_with_rag("retail analytics best practices", task)
        
        # Gather comprehensive retail data
        total_revenue = db.query(func.sum(Order.total_amount)).filter(
            Order.created_at >= datetime.utcnow() - timedelta(days=30),
            Order.status.in_(['Delivered', 'Shipped'])
        ).scalar() or 0
        
        total_orders = db.query(Order).filter(
            Order.created_at >= datetime.utcnow() - timedelta(days=30),
            Order.status.in_(['Delivered', 'Shipped'])
        ).count()
        
        data = {
            "last_30_days_revenue": float(total_revenue),
            "last_30_days_orders": total_orders,
            "avg_order_value": float(total_revenue) / total_orders if total_orders > 0 else 0
        }
        
        if self.llm_service and self.llm_service.is_available():
            result = self.llm_service.generate_with_rag(
                query=f"Provide strategic retail insights for: {json.dumps(data)}",
                system_prompt=self.system_prompt,
                k=3
            )
            
            return {
                "insights": result.get("response", "Insights unavailable"),
                "rag_enhanced": result.get("rag_used", False),
                "model_used": result.get("model", "unknown"),
                "data": data
            }
        
        return {"error": "LLM service not available", "data": data}


class AIMLInsightsAgent(BaseAIAgent):
    """AI-powered ML Insights Agent"""
    
    def __init__(self):
        super().__init__(
            name="ML Insights Agent",
            description="Advanced ML-driven predictions and insights",
            system_prompt="""You are an expert Machine Learning Insights AI Agent.
Your role is to provide ML-driven predictions, anomaly detection, and advanced analytics.

When generating insights:
1. Use statistical and ML models for predictions
2. Provide confidence intervals and uncertainty estimates
3. Explain model reasoning and key features
4. Detect anomalies with statistical significance
5. Forecast trends with appropriate time horizons

Always explain the methodology and confidence levels."""
        )
    
    def execute_task(self, task: AgentTask, db: Session) -> Dict[str, Any]:
        task_handlers = {
            "revenue_prediction": self.predict_revenue,
            "churn_prediction": self.predict_churn,
            "demand_forecast": self.forecast_demand,
            "ai_ml_analysis": self.ai_ml_analysis
        }
        
        handler = task_handlers.get(task.task_type)
        if handler:
            return handler(db, task.params, task)
        return {"error": f"Unknown task type: {task.task_type}"}
    
    def predict_revenue(self, db: Session, params: Dict[str, Any], task: AgentTask) -> Dict[str, Any]:
        """AI-powered revenue prediction"""
        days = params.get("days", 30)
        
        historical = db.query(func.sum(Order.total_amount)).filter(
            Order.created_at >= datetime.utcnow() - timedelta(days=30),
            Order.status.in_(['Delivered', 'Shipped'])
        ).scalar() or 0
        
        avg_daily = historical / 30 if historical > 0 else 5000
        
        data = {
            "historical_30_day_revenue": float(historical),
            "avg_daily_revenue": round(avg_daily, 2),
            "prediction_days": days,
            "simple_prediction": round(avg_daily * days, 2)
        }
        
        # AI-enhanced prediction
        if self.llm_service and self.llm_service.is_available():
            ai_result = self.analyze_with_llm(data, "Provide ML-based revenue prediction with confidence intervals")
            ai_prediction = ai_result.get("response", "AI prediction unavailable")
        else:
            ai_prediction = "AI prediction unavailable - using statistical baseline"
        
        data["ai_prediction"] = ai_prediction
        data["generated_at"] = datetime.utcnow().isoformat()
        
        return data
    
    def predict_churn(self, db: Session, params: Dict[str, Any], task: AgentTask) -> Dict[str, Any]:
        """AI-powered churn prediction"""
        sixty_days_ago = datetime.utcnow() - timedelta(days=60)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        
        users = db.query(User).all()
        at_risk = []
        
        for user in users:
            last_order = db.query(Order).filter(Order.user_id == user.id).order_by(Order.created_at.desc()).first()
            
            if last_order:
                days_since_last_order = (datetime.utcnow() - last_order.created_at).days
                risk_score = 0
                
                if days_since_last_order > 60:
                    risk_score += 50
                if days_since_last_order > 30:
                    risk_score += 30
                
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
        
        data = {
            "at_risk_customers": at_risk,
            "total_at_risk": len(at_risk),
            "total_customers": len(users)
        }
        
        # AI analysis
        if self.llm_service and self.llm_service.is_available():
            ai_result = self.analyze_with_llm(data, "Analyze churn risk and provide retention strategies")
            ai_strategy = ai_result.get("response", "AI analysis unavailable")
        else:
            ai_strategy = "AI insights unavailable"
        
        data["ai_retention_strategy"] = ai_strategy
        data["generated_at"] = datetime.utcnow().isoformat()
        
        return data
    
    def forecast_demand(self, db: Session, params: Dict[str, Any], task: AgentTask) -> Dict[str, Any]:
        """ML-powered demand forecasting"""
        try:
            from app.services.demand_forecasting_service import demand_forecasting_service
            
            periods = params.get("days", 30)
            model_type = params.get("model_type", "all")
            
            # Get forecast from existing service
            forecast_result = demand_forecasting_service.train_and_forecast(
                db=db,
                model_type=model_type,
                periods=periods
            )
            
            # AI insights on forecast
            if self.llm_service and self.llm_service.is_available():
                ai_result = self.analyze_with_llm(
                    forecast_result,
                    "Analyze forecast results and provide business recommendations"
                )
                ai_insights = ai_result.get("response", "AI analysis unavailable")
            else:
                ai_insights = "AI insights unavailable"
            
            forecast_result["ai_insights"] = ai_insights
            return forecast_result
            
        except Exception as e:
            return {"error": str(e)}
    
    def ai_ml_analysis(self, db: Session, params: Dict[str, Any], task: AgentTask) -> Dict[str, Any]:
        """Pure AI-driven ML analysis"""
        # Enhance with RAG
        context = self.enhance_with_rag("machine learning business analytics", task)
        
        if self.llm_service and self.llm_service.is_available():
            query = params.get("query", "Analyze business performance and provide ML insights")
            
            result = self.llm_service.generate_with_rag(
                query=query,
                system_prompt=self.system_prompt,
                k=3
            )
            
            return {
                "analysis": result.get("response", "Analysis unavailable"),
                "rag_enhanced": result.get("rag_used", False),
                "model_used": result.get("model", "unknown")
            }
        
        return {"error": "LLM service not available"}


class AIDocumentIntelligenceAgent(BaseAIAgent):
    """AI-powered Document Intelligence Agent using real document services"""
    
    def __init__(self):
        super().__init__(
            name="Document Intelligence Agent",
            description="AI-powered document analysis with real document processing",
            system_prompt="""You are an expert Document Intelligence AI Agent.
Your role is to analyze documents, search content, extract insights, and provide intelligent summaries.

When processing documents:
1. Search and retrieve relevant document content
2. Extract key entities, concepts, and relationships
3. Generate coherent summaries with key points
4. Identify actionable insights from document data
5. Provide context-aware analysis based on actual document content

Focus on extracting valuable information from real document content."""
        )
        # Import document intelligence service
        try:
            from app.services.document_intelligence_panel_service import document_intelligence_service
            self.doc_service = document_intelligence_service
        except ImportError:
            self.doc_service = None
            logger.warning("Document intelligence service not available")
    
    def execute_task(self, task: AgentTask, db: Session) -> Dict[str, Any]:
        task_handlers = {
            "analyze_documents": self.analyze_documents,
            "search_documents": self.search_documents,
            "generate_ai_summary": self.generate_ai_summary,
            "extract_keywords": self.extract_keywords,
            "summarize_content": self.summarize_content,
            "get_document_stats": self.get_document_stats
        }

        handler = task_handlers.get(task.task_type)
        if handler:
            return handler(db, task.params, task)
        return {"error": f"Unknown task type: {task.task_type}"}
    
    def analyze_documents(self, db: Session, params: Dict[str, Any], task: AgentTask) -> Dict[str, Any]:
        """Analyze documents using real document intelligence service"""
        try:
            if not self.doc_service:
                return {"error": "Document intelligence service not available"}
            
            # Get real document data from service
            documents = self.doc_service.list_documents(db)
            
            # Get document statistics
            stats = {
                "total_documents": len(documents),
                "processed": len([d for d in documents if d.get('status') == 'processed']),
                "indexed": len([d for d in documents if d.get('status') == 'indexed']),
                "by_type": {}
            }
            
            # Count by document type
            for doc in documents:
                doc_type = doc.get('document_type', 'unknown')
                stats["by_type"][doc_type] = stats["by_type"].get(doc_type, 0) + 1
            
            # AI analysis using LLM
            ai_insights = "AI analysis unavailable"
            if self.llm_service and self.llm_service.is_available() and documents:
                analysis_data = {
                    "document_stats": stats,
                    "sample_documents": documents[:5]
                }
                ai_result = self.analyze_with_llm(
                    analysis_data, 
                    "Analyze this document collection. What patterns do you see? What insights can you provide about the document types and processing status?"
                )
                ai_insights = ai_result.get("response", ai_insights)
            
            return {
                "stats": stats,
                "documents": documents[:10],
                "ai_insights": ai_insights,
                "generated_at": datetime.utcnow().isoformat(),
                "source": "document_intelligence_service"
            }
        except Exception as e:
            logger.error(f"Document analysis error: {e}")
            return {"error": str(e), "message": "Document analysis failed"}
    
    def search_documents(self, db: Session, params: Dict[str, Any], task: AgentTask) -> Dict[str, Any]:
        """Search documents using real document search"""
        try:
            if not self.doc_service:
                return {"error": "Document intelligence service not available"}
            
            query = params.get("query", "")
            document_type = params.get("document_type")
            show_all = params.get("show_all", False)
            
            if not query:
                return {"error": "No search query provided"}
            
            # Perform real document search
            results = self.doc_service.search_documents(
                db=db,
                query=query,
                document_type=document_type,
                limit=10,
                show_all_matches=show_all
            )
            
            # Generate AI summary of search results
            ai_summary = None
            if self.llm_service and self.llm_service.is_available() and results:
                # Prepare context for AI
                matches_summary = []
                for r in results:
                    matches_summary.append({
                        "filename": r.get("filename"),
                        "matches": r.get("match_count", 0),
                        "type": r.get("document_type")
                    })
                
                prompt = f"""Based on the search for "{query}" in {len(results)} documents, provide a brief summary of what was found and any patterns or insights.

Documents found: {len(results)}
Top matches: {matches_summary[:3]}

Provide a 2-3 sentence summary of the search results."""
                
                result = self.llm_service.generate_response(
                    prompt=prompt,
                    system_prompt=self.system_prompt
                )
                ai_summary = result.get("response")
            
            return {
                "query": query,
                "results_count": len(results),
                "results": results,
                "ai_summary": ai_summary,
                "search_method": "document_intelligence_ocr_search",
                "generated_at": datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"Document search error: {e}")
            return {"error": str(e), "message": "Document search failed"}
    
    def generate_ai_summary(self, db: Session, params: Dict[str, Any], task: AgentTask) -> Dict[str, Any]:
        """Generate AI summary for a search query based on document content"""
        try:
            query = params.get("query", "")
            search_results = params.get("search_results", [])
            
            if not query:
                return {"error": "No query provided for summary"}
            
            if not search_results:
                return {
                    "query": query,
                    "summary": f"No documents found containing '{query}'. Try a different search term.",
                    "insights": [],
                    "suggestions": ["Try broader keywords", "Check document processing status"]
                }
            
            # Prepare context from search results
            context_parts = []
            total_matches = 0
            document_types = set()
            
            for result in search_results:
                matches = result.get("all_matches", result.get("initial_matches", []))
                total_matches += len(matches)
                document_types.add(result.get("document_type", "unknown"))
                
                # Add snippets from matches
                for match in matches[:3]:  # Top 3 matches per document
                    snippet = match.get("snippet", "")
                    if snippet:
                        context_parts.append(snippet[:200])
            
            context = "\n".join(context_parts[:10])  # Limit context
            
            summary_text = f"Found '{query}' in {len(search_results)} document(s) with {total_matches} total matches."
            insights = []
            
            # Use LLM for enhanced summary if available
            if self.llm_service and self.llm_service.is_available():
                prompt = f"""Analyze these search results for "{query}" and provide insights.

Context from documents:
{context}

Provide:
1. A 2-3 sentence summary of what was found
2. 3-5 key insights or observations about the content
3. Any patterns or notable information

Format as JSON with 'summary' and 'insights' array."""
                
                try:
                    result = self.llm_service.create_structured_output(
                        prompt=prompt,
                        output_schema={
                            "summary": "string",
                            "insights": ["string"]
                        }
                    )
                    
                    structured = result.get("structured_output", {})
                    summary_text = structured.get("summary", summary_text)
                    insights = structured.get("insights", insights)
                except Exception as e:
                    logger.warning(f"LLM summary generation failed: {e}")
                    insights = [f"Documents span types: {', '.join(document_types)}"]
            else:
                insights = [
                    f"Found {total_matches} mentions across {len(search_results)} documents",
                    f"Document types: {', '.join(document_types)}"
                ]
            
            return {
                "query": query,
                "summary": summary_text,
                "insights": insights,
                "document_count": len(search_results),
                "total_matches": total_matches,
                "document_types": list(document_types),
                "generated_at": datetime.utcnow().isoformat(),
                "ai_enhanced": self.llm_service is not None and self.llm_service.is_available()
            }
        except Exception as e:
            logger.error(f"AI summary generation error: {e}")
            return {
                "query": params.get("query", ""),
                "summary": f"Search completed but summary generation failed.",
                "error": str(e)
            }
    
    def get_document_stats(self, db: Session, params: Dict[str, Any], task: AgentTask) -> Dict[str, Any]:
        """Get document statistics from real service"""
        try:
            if not self.doc_service:
                return {"error": "Document service not available"}
            
            documents = self.doc_service.list_documents(db)
            
            stats = {
                "total": len(documents),
                "by_status": {},
                "by_type": {},
                "recent_uploads": []
            }
            
            for doc in documents:
                status = doc.get("status", "unknown")
                doc_type = doc.get("document_type", "unknown")
                
                stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
                stats["by_type"][doc_type] = stats["by_type"].get(doc_type, 0) + 1
            
            # Sort by upload date for recent
            sorted_docs = sorted(
                documents, 
                key=lambda x: x.get("upload_date", ""), 
                reverse=True
            )
            stats["recent_uploads"] = sorted_docs[:5]
            
            return {
                "stats": stats,
                "generated_at": datetime.utcnow().isoformat()
            }
        except Exception as e:
            return {"error": str(e)}
    
    def extract_keywords(self, db: Session, params: Dict[str, Any], task: AgentTask) -> Dict[str, Any]:
        """AI-powered keyword extraction from document content"""
        text = params.get("text", "")
        
        if not text:
            return {"error": "No text provided"}
        
        if self.llm_service and self.llm_service.is_available():
            prompt = f"""Extract key topics, entities, and important keywords from the following text.
Return a JSON array of objects with 'keyword', 'category' (entity/topic/concept), and 'importance' (1-10).

Text: {text[:2000]}"""
            
            result = self.llm_service.create_structured_output(
                prompt=prompt,
                output_schema={
                    "keywords": [
                        {"keyword": "string", "category": "string", "importance": 1}
                    ]
                }
            )
            
            return {
                "keywords": result.get("structured_output", {}).get("keywords", []),
                "raw_response": result.get("response"),
                "success": result.get("success")
            }
        
        # Fallback to simple extraction
        import re
        words = re.findall(r'\b[A-Za-z]{4,}\b', text.lower())
        word_counts = {}
        for word in words:
            word_counts[word] = word_counts.get(word, 0) + 1
        
        top_keywords = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:20]
        
        return {
            "keywords": [{"keyword": word, "count": count} for word, count in top_keywords],
            "method": "simple_extraction",
            "ai_enhanced": False
        }
    
    def summarize_content(self, db: Session, params: Dict[str, Any], task: AgentTask) -> Dict[str, Any]:
        """AI-powered content summarization"""
        text = params.get("text", "")
        max_length = params.get("max_length", 200)

        if not text:
            return {"error": "No text provided"}

        if self.llm_service and self.llm_service.is_available():
            prompt = f"""Summarize the following content in about {max_length} words.
Focus on key points, main arguments, and actionable insights.

Content: {text[:3000]}"""

            result = self.llm_service.generate_response(
                prompt=prompt,
                system_prompt=self.system_prompt
            )

            return {
                "summary": result.get("response", "Summary unavailable"),
                "original_length": len(text),
                "success": result.get("success")
            }

        return {"error": "LLM service not available for summarization"}


class AIMultiAgentControlCenter:
    """AI-powered central orchestration hub with MCP-like protocol"""
    
    def __init__(self):
        self.agents: Dict[str, BaseAIAgent] = {
            "inventory": AIInventoryAgent(),
            "retail_analyst": AIRetailAnalystAgent(),
            "ml_insights": AIMLInsightsAgent(),
            "document_intelligence": AIDocumentIntelligenceAgent()
        }
        self.task_queue: List[AgentTask] = []
        self.orchestration_logs: List[Dict[str, Any]] = []
        self.agent_communications: List[AgentMessage] = []
        self.llm_service = llm_service if AI_AVAILABLE else None
        
        logger.info(f"AI Multi-Agent Control Center initialized with {len(self.agents)} agents")
    
    def get_agent_status(self) -> Dict[str, Any]:
        """Get status of all agents"""
        return {
            "agents": {name: agent.get_status() for name, agent in self.agents.items()},
            "total_agents": len(self.agents),
            "active_agents": sum(1 for a in self.agents.values() if a.status == AgentStatus.ACTIVE),
            "busy_agents": sum(1 for a in self.agents.values() if a.status == AgentStatus.BUSY),
            "queue_length": len(self.task_queue),
            "ai_available": self.llm_service is not None and self.llm_service.is_available(),
            "rag_available": self.llm_service is not None and self.llm_service.vectorstore is not None
        }
    
    def execute_task(self, agent_name: str, task_type: str, params: Dict[str, Any], db: Session) -> Dict[str, Any]:
        """Execute a task through a specific agent with full tracking"""
        if agent_name not in self.agents:
            return {"error": f"Agent {agent_name} not found"}
        
        agent = self.agents[agent_name]
        task = AgentTask(agent_name=agent_name, task_type=task_type, params=params)
        
        # Update agent status
        agent.status = AgentStatus.BUSY
        agent.last_activity = datetime.utcnow()
        
        logger.info(f"Executing task {task_type} on agent {agent_name}")
        
        try:
            # Execute task
            result = agent.execute_task(task, db)
            
            # Update task status
            task.result = result
            task.status = "completed"
            task.completed_at = datetime.utcnow()
            agent.tasks_completed += 1
            agent.status = AgentStatus.ACTIVE
            
            # Broadcast completion to other agents (MCP protocol)
            self._broadcast_task_completion(agent_name, task_type, result)
            
        except Exception as e:
            logger.error(f"Task execution failed: {e}")
            task.error = str(e)
            task.status = "failed"
            agent.tasks_failed += 1
            agent.status = AgentStatus.ERROR
            agent.health_score = max(0, agent.health_score - 10)
            result = {"error": str(e)}
        
        self.task_queue.append(task)
        
        # Log orchestration
        self.orchestration_logs.append({
            "timestamp": datetime.utcnow().isoformat(),
            "agent": agent_name,
            "task": task_type,
            "status": task.status,
            "task_id": task.id,
            "rag_enhanced": task.rag_context is not None
        })
        
        return {
            "task_id": task.id,
            "status": task.status,
            "result": result,
            "error": task.error,
            "agent": agent_name,
            "task_type": task_type,
            "rag_enhanced": task.rag_context is not None,
            "execution_time": (task.completed_at - task.created_at).total_seconds() if task.completed_at else None
        }
    
    def _broadcast_task_completion(self, from_agent: str, task_type: str, result: Dict[str, Any]):
        """Broadcast task completion to other agents (MCP protocol)"""
        for agent_name, agent in self.agents.items():
            if agent_name != from_agent:
                message = AgentMessage(
                    from_agent=from_agent,
                    to_agent=agent_name,
                    message_type="task_complete",
                    content={"task_type": task_type, "summary": str(result)[:200]}
                )
                agent.receive_message(message)
                self.agent_communications.append(message)
    
    def orchestrate_multi_agent_task(self, task_plan: List[Dict[str, Any]], db: Session) -> Dict[str, Any]:
        """Orchestrate a complex task across multiple agents"""
        results = []
        
        for step in task_plan:
            agent_name = step.get("agent")
            task_type = step.get("task")
            params = step.get("params", {})
            
            # Execute task
            result = self.execute_task(agent_name, task_type, params, db)
            results.append(result)
            
            # If step failed, stop orchestration
            if result.get("status") == "failed":
                break
        
        return {
            "orchestration_id": str(uuid.uuid4()),
            "steps_executed": len(results),
            "results": results,
            "success": all(r.get("status") == "completed" for r in results)
        }
    
    def get_task_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent task execution history"""
        tasks = sorted(self.task_queue, key=lambda t: t.created_at, reverse=True)[:limit]
        return [task.to_dict() for task in tasks]
    
    def get_orchestration_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get orchestration logs"""
        return sorted(self.orchestration_logs, key=lambda x: x["timestamp"], reverse=True)[:limit]
    
    def get_agent_communications(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get inter-agent communications (MCP protocol logs)"""
        comms = sorted(self.agent_communications, key=lambda x: x.timestamp, reverse=True)[:limit]
        return [
            {
                "from": c.from_agent,
                "to": c.to_agent,
                "type": c.message_type,
                "content": c.content,
                "timestamp": c.timestamp.isoformat(),
                "message_id": c.message_id
            }
            for c in comms
        ]
    
    def submit_task(self, agent_name: str, task_type: str, params: Dict[str, Any], db: Session) -> Dict[str, Any]:
        """Submit a task to an agent - alias for execute_task"""
        return self.execute_task(agent_name, task_type, params, db)
    
    def reset_agent(self, agent_name: str) -> bool:
        """Reset an agent to idle state"""
        if agent_name in self.agents:
            self.agents[agent_name].status = AgentStatus.IDLE
            self.agents[agent_name].health_score = 100
            self.agents[agent_name].message_queue.clear()
            return True
        return False
    
    def add_to_knowledge_base(self, agent_name: str, content: str) -> bool:
        """Add content to an agent's knowledge base"""
        if agent_name in self.agents:
            self.agents[agent_name].knowledge_base.append(content)
            
            # Also add to vector store if available
            if self.llm_service and self.llm_service.vectorstore:
                return self.llm_service.vectorstore.add_documents(
                    documents=[content],
                    metadatas=[{"agent": agent_name, "timestamp": datetime.utcnow().isoformat()}]
                )
            return True
        return False


# Global AI control center instance
ai_multi_agent_center = AIMultiAgentControlCenter()
