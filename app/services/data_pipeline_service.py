"""
Data Pipeline Service - Azure Data Engineering Integration
Real-time data pipeline orchestration with Azure Data Factory, Databricks, and Delta Lake
"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
import requests
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Order, OrderItem, Product, User, SupportTicket

logger = logging.getLogger(__name__)


class PipelineStatus(Enum):
    """Pipeline execution status"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DataLayer(Enum):
    """Medallion architecture layers"""
    RAW = "raw"
    STAGING = "staging"
    CURATED = "curated"


@dataclass
class PipelineRun:
    """Pipeline run information"""
    run_id: str
    pipeline_name: str
    status: PipelineStatus
    start_time: datetime
    end_time: Optional[datetime] = None
    records_processed: int = 0
    error_message: Optional[str] = None


@dataclass
class DataQualityReport:
    """Data quality check results"""
    execution_date: str
    total_checks: int
    passed_checks: int
    failed_checks: int
    quality_score: float
    critical_failures: int
    status: str


class DataPipelineService:
    """
    Service for managing Azure Data Engineering pipeline
    Integrates with Data Factory, Databricks, and Delta Lake
    """
    
    def __init__(self):
        self.azure_tenant_id = settings.azure_tenant_id
        self.azure_client_id = settings.azure_client_id
        self.azure_client_secret = settings.azure_client_secret
        self.storage_account = getattr(settings, 'azure_storage_account', 'smartretailstore')
        self.workspace_url = getattr(settings, 'databricks_workspace_url', None)
        
        # Layer paths in ADLS Gen2
        self.raw_path = f"abfss://raw@{self.storage_account}.dfs.core.windows.net"
        self.staging_path = f"abfss://staging@{self.storage_account}.dfs.core.windows.net"
        self.curated_path = f"abfss://curated@{self.storage_account}.dfs.core.windows.net"
        
        # Access token cache
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
    
    def get_azure_access_token(self) -> Optional[str]:
        """Get Azure AD access token for API calls"""
        if self._access_token and self._token_expiry and datetime.utcnow() < self._token_expiry:
            return self._access_token
        
        if not all([self.azure_tenant_id, self.azure_client_id, self.azure_client_secret]):
            logger.warning("Azure credentials not configured")
            return None
        
        try:
            url = f"https://login.microsoftonline.com/{self.azure_tenant_id}/oauth2/token"
            data = {
                "grant_type": "client_credentials",
                "client_id": self.azure_client_id,
                "client_secret": self.azure_client_secret,
                "resource": "https://management.azure.com/"
            }
            
            response = requests.post(url, data=data, timeout=30)
            response.raise_for_status()
            
            token_data = response.json()
            self._access_token = token_data.get("access_token")
            expires_in = token_data.get("expires_in", 3600)
            self._token_expiry = datetime.utcnow() + timedelta(seconds=expires_in - 300)
            
            return self._access_token
        except Exception as e:
            logger.error(f"Failed to get Azure token: {e}")
            return None
    
    def trigger_adf_pipeline(self, pipeline_name: str, parameters: Dict = None) -> Optional[str]:
        """Trigger Azure Data Factory pipeline run"""
        token = self.get_azure_access_token()
        if not token:
            return None
        
        try:
            subscription_id = getattr(settings, 'azure_subscription_id', '')
            resource_group = getattr(settings, 'azure_resource_group', '')
            factory_name = getattr(settings, 'adf_factory_name', 'SmartRetail-ADF')
            
            url = (
                f"https://management.azure.com/subscriptions/{subscription_id}/"
                f"resourceGroups/{resource_group}/providers/Microsoft.DataFactory/"
                f"factories/{factory_name}/pipelines/{pipeline_name}/createRun"
                f"?api-version=2018-06-01"
            )
            
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            body = {"parameters": parameters or {}}
            
            response = requests.post(url, headers=headers, json=body, timeout=30)
            response.raise_for_status()
            
            run_id = response.json().get("runId")
            logger.info(f"Triggered ADF pipeline {pipeline_name}, run ID: {run_id}")
            return run_id
        except Exception as e:
            logger.error(f"Failed to trigger ADF pipeline: {e}")
            return None
    
    def get_pipeline_status(self, pipeline_name: str, run_id: str) -> Optional[PipelineRun]:
        """Get pipeline run status from ADF"""
        token = self.get_azure_access_token()
        if not token:
            return None
        
        try:
            subscription_id = getattr(settings, 'azure_subscription_id', '')
            resource_group = getattr(settings, 'azure_resource_group', '')
            factory_name = getattr(settings, 'adf_factory_name', 'SmartRetail-ADF')
            
            url = (
                f"https://management.azure.com/subscriptions/{subscription_id}/"
                f"resourceGroups/{resource_group}/providers/Microsoft.DataFactory/"
                f"factories/{factory_name}/pipelineruns/{run_id}"
                f"?api-version=2018-06-01"
            )
            
            headers = {"Authorization": f"Bearer {token}"}
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            return PipelineRun(
                run_id=run_id,
                pipeline_name=pipeline_name,
                status=PipelineStatus(data.get("status", "unknown").lower()),
                start_time=datetime.fromisoformat(data.get("runStart", datetime.utcnow().isoformat())),
                end_time=datetime.fromisoformat(data.get("runEnd")) if data.get("runEnd") else None,
                records_processed=data.get("userProperties", {}).get("recordsProcessed", 0),
                error_message=data.get("message")
            )
        except Exception as e:
            logger.error(f"Failed to get pipeline status: {e}")
            return None
    
    def run_databricks_notebook(self, notebook_path: str, parameters: Dict = None) -> Optional[str]:
        """Run Databricks notebook via API"""
        if not self.workspace_url:
            logger.warning("Databricks workspace URL not configured")
            return None
        
        token = getattr(settings, 'databricks_token', None)
        if not token:
            logger.warning("Databricks token not configured")
            return None
        
        try:
            url = f"{self.workspace_url}/api/2.1/jobs/runs/submit"
            headers = {"Authorization": f"Bearer {token}"}
            
            body = {
                "run_name": f"Pipeline_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
                "existing_cluster_id": getattr(settings, 'databricks_cluster_id', ''),
                "notebook_task": {
                    "notebook_path": notebook_path,
                    "base_parameters": parameters or {}
                }
            }
            
            response = requests.post(url, headers=headers, json=body, timeout=30)
            response.raise_for_status()
            
            run_id = response.json().get("run_id")
            logger.info(f"Started Databricks notebook {notebook_path}, run ID: {run_id}")
            return str(run_id)
        except Exception as e:
            logger.error(f"Failed to run Databricks notebook: {e}")
            return None


class LocalDataPipelineService:
    """
    Local implementation of data pipeline when Azure is not configured
    Simulates the medallion architecture using SQLite database
    """
    
    def __init__(self):
        self.pipeline_service = DataPipelineService()
    
    def extract_raw_data(self, db: Session) -> Dict[str, List[Dict]]:
        """Extract raw data from SQLite (simulates Bronze layer)"""
        logger.info("Extracting raw data from database...")
        
        # Extract orders
        orders = db.query(Order).all()
        orders_data = [{
            "id": o.id,
            "order_number": o.order_number,
            "user_id": o.user_id,
            "customer_name": o.customer_name,
            "status": o.status,
            "total_amount": o.total_amount,
            "payment_method": o.payment_method,
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "items": [{
                "product_id": item.product_id,
                "product_name": item.product_name,
                "quantity": item.quantity,
                "unit_price": item.unit_price
            } for item in o.items]
        } for o in orders]
        
        # Extract products
        products = db.query(Product).all()
        products_data = [{
            "id": p.id,
            "sku": p.sku,
            "name": p.name,
            "category": p.category,
            "price": p.price,
            "stock": p.stock,
            "created_at": p.created_at.isoformat() if p.created_at else None
        } for p in products]
        
        # Extract users
        users = db.query(User).all()
        users_data = [{
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "is_admin": u.is_admin,
            "created_at": u.created_at.isoformat() if u.created_at else None
        } for u in users]
        
        # Extract tickets
        tickets = db.query(SupportTicket).all()
        tickets_data = [{
            "id": t.id,
            "ticket_number": t.ticket_number,
            "customer_email": t.customer_email,
            "subject": t.subject,
            "status": t.status,
            "priority": t.priority,
            "sentiment": getattr(t, 'sentiment', 'neutral'),
            "created_at": t.created_at.isoformat() if t.created_at else None
        } for t in tickets]
        
        return {
            "orders": orders_data,
            "products": products_data,
            "users": users_data,
            "support_tickets": tickets_data,
            "extraction_timestamp": datetime.utcnow().isoformat(),
            "total_records": len(orders_data) + len(products_data) + len(users_data) + len(tickets_data)
        }
    
    def transform_to_staging(self, raw_data: Dict) -> Dict[str, Any]:
        """Transform raw data to staging format (Silver layer simulation)"""
        logger.info("Transforming data to staging format...")
        
        # Transform customers with metrics
        customers_staging = []
        for user in raw_data["users"]:
            user_orders = [o for o in raw_data["orders"] if o["user_id"] == user["id"]]
            total_orders = len(user_orders)
            total_spent = sum(o["total_amount"] for o in user_orders)
            avg_order_value = total_spent / total_orders if total_orders > 0 else 0
            
            # Customer segmentation
            if total_spent > 10000:
                segment = "VIP"
            elif total_spent > 5000:
                segment = "Gold"
            elif total_spent > 1000:
                segment = "Silver"
            else:
                segment = "Bronze"
            
            customers_staging.append({
                **user,
                "total_orders": total_orders,
                "total_spent": round(total_spent, 2),
                "avg_order_value": round(avg_order_value, 2),
                "customer_segment": segment,
                "effective_date": datetime.utcnow().date().isoformat(),
                "is_current": True
            })
        
        # Transform products with metrics
        products_staging = []
        for product in raw_data["products"]:
            # Calculate sales from order items
            items_sold = sum(
                item["quantity"]
                for order in raw_data["orders"]
                for item in order["items"]
                if item["product_id"] == product["id"]
            )
            
            revenue = sum(
                item["quantity"] * item["unit_price"]
                for order in raw_data["orders"]
                for item in order["items"]
                if item["product_id"] == product["id"]
            )
            
            # Stock status
            if product["stock"] == 0:
                stock_status = "Out of Stock"
            elif product["stock"] < 10:
                stock_status = "Low Stock"
            elif product["stock"] < 50:
                stock_status = "Medium Stock"
            else:
                stock_status = "In Stock"
            
            products_staging.append({
                **product,
                "total_sold": items_sold,
                "total_revenue": round(revenue, 2),
                "inventory_value": round(product["stock"] * product["price"], 2),
                "stock_status": stock_status,
                "effective_date": datetime.utcnow().date().isoformat(),
                "is_current": True
            })
        
        # Transform orders with profit calculations
        orders_staging = []
        for order in raw_data["orders"]:
            total_items = sum(item["quantity"] for item in order["items"])
            distinct_products = len(set(item["product_id"] for item in order["items"]))
            
            # Calculate profit (assume 40% margin)
            order_profit = sum(
                item["quantity"] * item["unit_price"] * 0.4
                for item in order["items"]
            )
            
            created_dt = datetime.fromisoformat(order["created_at"]) if order["created_at"] else datetime.utcnow()
            
            orders_staging.append({
                **order,
                "total_items": total_items,
                "distinct_products": distinct_products,
                "order_profit": round(order_profit, 2),
                "order_year": created_dt.year,
                "order_month": created_dt.month,
                "is_weekend": created_dt.weekday() >= 5
            })
        
        return {
            "dim_customers": customers_staging,
            "dim_products": products_staging,
            "fact_orders": orders_staging,
            "fact_support_tickets": raw_data["support_tickets"],
            "transform_timestamp": datetime.utcnow().isoformat()
        }
    
    def curate_analytics_data(self, staging_data: Dict) -> Dict[str, Any]:
        """Create curated analytics datasets (Gold layer simulation)"""
        logger.info("Creating curated analytics datasets...")
        
        # Daily sales aggregation
        from collections import defaultdict
        daily_sales = defaultdict(lambda: {
            "total_orders": 0,
            "total_revenue": 0.0,
            "total_profit": 0.0,
            "unique_customers": set(),
            "delivered": 0,
            "cancelled": 0
        })
        
        for order in staging_data["fact_orders"]:
            date_key = order["created_at"][:10] if order["created_at"] else "unknown"
            daily_sales[date_key]["total_orders"] += 1
            daily_sales[date_key]["total_revenue"] += order["total_amount"]
            daily_sales[date_key]["total_profit"] += order.get("order_profit", 0)
            daily_sales[date_key]["unique_customers"].add(order["user_id"])
            
            if order["status"] == "Delivered":
                daily_sales[date_key]["delivered"] += 1
            elif order["status"] == "Cancelled":
                daily_sales[date_key]["cancelled"] += 1
        
        sales_daily = []
        for date_key, metrics in sorted(daily_sales.items()):
            total = metrics["total_orders"]
            sales_daily.append({
                "created_at": date_key,
                "total_orders": total,
                "total_revenue": round(metrics["total_revenue"], 2),
                "avg_order_value": round(metrics["total_revenue"] / total, 2) if total > 0 else 0,
                "unique_customers": len(metrics["unique_customers"]),
                "delivered_orders": metrics["delivered"],
                "cancelled_orders": metrics["cancelled"],
                "cancellation_rate": round((metrics["cancelled"] / total) * 100, 2) if total > 0 else 0,
                "total_profit": round(metrics["total_profit"], 2)
            })
        
        # Customer 360 with RFM analysis
        customer_360 = []
        for customer in staging_data["dim_customers"]:
            # Calculate RFM
            recency = 30  # Simplified - days since last order
            frequency = customer["total_orders"]
            monetary = customer["total_spent"]
            
            # Simplified scoring
            r_score = 5 if recency < 7 else 4 if recency < 30 else 3 if recency < 60 else 2 if recency < 90 else 1
            f_score = 5 if frequency > 10 else 4 if frequency > 5 else 3 if frequency > 2 else 2 if frequency > 0 else 1
            m_score = 5 if monetary > 10000 else 4 if monetary > 5000 else 3 if monetary > 2000 else 2 if monetary > 500 else 1
            
            rfm_segment = "Average"
            if r_score >= 4 and f_score >= 4 and m_score >= 4:
                rfm_segment = "Champions"
            elif f_score >= 4:
                rfm_segment = "Loyal Customers"
            elif r_score >= 4:
                rfm_segment = "New Customers"
            elif r_score <= 2:
                rfm_segment = "At Risk"
            
            # Churn risk
            churn_risk = 0.1
            if rfm_segment == "At Risk":
                churn_risk = 0.8
            elif r_score < 3:
                churn_risk = 0.5
            
            customer_360.append({
                **customer,
                "recency": recency,
                "frequency": frequency,
                "monetary": monetary,
                "r_score": r_score,
                "f_score": f_score,
                "m_score": m_score,
                "rfm_score": f"{r_score}{f_score}{m_score}",
                "rfm_segment": rfm_segment,
                "churn_risk_score": round(churn_risk, 2),
                "churn_risk_segment": "High Risk" if churn_risk > 0.7 else "Medium Risk" if churn_risk > 0.4 else "Low Risk"
            })
        
        # Inventory analytics
        inventory_analytics = []
        for product in staging_data["dim_products"]:
            daily_velocity = product["total_sold"] / 90 if product["total_sold"] > 0 else 0
            days_inventory = product["stock"] / daily_velocity if daily_velocity > 0 else 999
            
            reorder = days_inventory < 30 or product["stock"] < 10
            
            inventory_analytics.append({
                **product,
                "daily_velocity": round(daily_velocity, 2),
                "days_of_inventory": round(days_inventory, 1),
                "abc_classification": "A" if product["total_revenue"] > 50000 else "B" if product["total_revenue"] > 10000 else "C",
                "reorder_recommended": reorder,
                "suggested_reorder_qty": max(0, int(daily_velocity * 60 - product["stock"])) if reorder else 0
            })
        
        # Anomaly detection features
        anomaly_features = []
        revenues = [d["total_revenue"] for d in sales_daily]
        if len(revenues) > 7:
            import statistics
            mean_revenue = statistics.mean(revenues)
            std_revenue = statistics.stdev(revenues) if len(revenues) > 1 else 1
            
            for i, day in enumerate(sales_daily):
                z_score = (day["total_revenue"] - mean_revenue) / max(std_revenue, 1)
                
                anomaly_features.append({
                    "created_at": day["created_at"],
                    "total_revenue": day["total_revenue"],
                    "total_orders": day["total_orders"],
                    "revenue_zscore": round(z_score, 2),
                    "is_anomaly": abs(z_score) > 2.5,
                    "severity": "High" if abs(z_score) > 3 else "Medium" if abs(z_score) > 2.5 else "Low"
                })
        
        return {
            "sales_daily": sales_daily,
            "customer_360": customer_360,
            "inventory_analytics": inventory_analytics,
            "anomaly_features": anomaly_features,
            "curated_timestamp": datetime.utcnow().isoformat(),
            "total_curated_records": len(sales_daily) + len(customer_360) + len(inventory_analytics) + len(anomaly_features)
        }
    
    def run_full_pipeline(self, db: Session) -> Dict[str, Any]:
        """Execute full medallion pipeline: Raw → Staging → Curated"""
        logger.info("Starting full data pipeline execution...")
        
        start_time = datetime.utcnow()
        
        # Step 1: Extract (Bronze)
        raw_data = self.extract_raw_data(db)
        
        # Step 2: Transform (Silver)
        staging_data = self.transform_to_staging(raw_data)
        
        # Step 3: Curate (Gold)
        curated_data = self.curate_analytics_data(staging_data)
        
        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()
        
        result = {
            "status": "success",
            "execution_id": f"pipeline_{start_time.strftime('%Y%m%d_%H%M%S')}",
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": duration,
            "layers": {
                "raw": {
                    "tables": ["orders", "products", "users", "support_tickets"],
                    "total_records": raw_data["total_records"]
                },
                "staging": {
                    "tables": ["dim_customers", "dim_products", "fact_orders", "fact_support_tickets"],
                    "total_records": sum(len(v) for k, v in staging_data.items() if isinstance(v, list))
                },
                "curated": {
                    "tables": ["sales_daily", "customer_360", "inventory_analytics", "anomaly_features"],
                    "total_records": curated_data["total_curated_records"]
                }
            },
            "data": curated_data  # Include curated data for downstream use
        }
        
        logger.info(f"Pipeline completed in {duration:.2f}s, processed {curated_data['total_curated_records']} records")
        return result
    
    def get_data_quality_report(self, curated_data: Dict) -> DataQualityReport:
        """Generate data quality report from curated data"""
        checks = []
        
        # Check 1: Sales data completeness
        sales = curated_data.get("sales_daily", [])
        if sales:
            non_null_revenue = sum(1 for s in sales if s.get("total_revenue", 0) > 0)
            checks.append(non_null_revenue == len(sales))
        
        # Check 2: Customer segmentation coverage
        customers = curated_data.get("customer_360", [])
        if customers:
            segmented = sum(1 for c in customers if c.get("rfm_segment"))
            checks.append(segmented == len(customers))
        
        # Check 3: Inventory stock status
        inventory = curated_data.get("inventory_analytics", [])
        if inventory:
            valid_status = sum(1 for i in inventory if i.get("stock_status"))
            checks.append(valid_status == len(inventory))
        
        passed = sum(checks)
        total = len(checks)
        quality_score = (passed / total * 100) if total > 0 else 100
        
        return DataQualityReport(
            execution_date=datetime.utcnow().date().isoformat(),
            total_checks=total,
            passed_checks=passed,
            failed_checks=total - passed,
            quality_score=quality_score,
            critical_failures=0,
            status="PASS" if quality_score >= 95 else "WARNING" if quality_score >= 90 else "FAIL"
        )
    
    def export_for_powerbi(self, curated_data: Dict) -> Dict[str, List[Dict]]:
        """Export curated data in Power BI friendly format"""
        return {
            "sales_daily": curated_data.get("sales_daily", []),
            "customer_360": curated_data.get("customer_360", []),
            "inventory_analytics": curated_data.get("inventory_analytics", []),
            "anomaly_features": curated_data.get("anomaly_features", []),
            "export_timestamp": datetime.utcnow().isoformat()
        }


# Real-time Pipeline Manager with Caching
class RealtimePipelineManager:
    """
    Manages real-time data pipeline with automatic refresh
    Keeps data fresh by running pipeline on schedule or on-demand
    """
    
    def __init__(self, refresh_interval_minutes: int = 5):
        self.refresh_interval = timedelta(minutes=refresh_interval_minutes)
        self._cache: Optional[Dict] = None
        self._last_run: Optional[datetime] = None
        self._is_running = False
        self._lock = threading.Lock()
        self._scheduler_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
    
    def get_data(self, db: Session, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Get pipeline data - from cache if fresh, or run new pipeline
        """
        with self._lock:
            # Check if cache is valid
            cache_valid = (
                self._cache is not None and 
                self._last_run is not None and 
                datetime.utcnow() - self._last_run < self.refresh_interval and
                not force_refresh
            )
            
            if cache_valid:
                logger.info("Returning cached pipeline data (age: %s)", 
                           datetime.utcnow() - self._last_run)
                return self._cache
            
            # Run fresh pipeline
            if self._is_running:
                logger.info("Pipeline already running, returning cached data")
                return self._cache or {"status": "pending", "message": "Pipeline running"}
            
            self._is_running = True
        
        try:
            logger.info("Running fresh pipeline...")
            result = local_pipeline_service.run_full_pipeline(db)
            
            with self._lock:
                self._cache = result
                self._last_run = datetime.utcnow()
                self._is_running = False
            
            return result
            
        except Exception as e:
            logger.error(f"Pipeline execution failed: {e}")
            with self._lock:
                self._is_running = False
            
            # Return cached data if available, else error
            if self._cache:
                return {**self._cache, "stale": True, "error": str(e)}
            raise
    
    def start_scheduler(self, db_session_factory):
        """Start background scheduler for continuous updates"""
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            logger.warning("Scheduler already running")
            return
        
        self._stop_event.clear()
        self._scheduler_thread = threading.Thread(
            target=self._scheduler_loop, 
            args=(db_session_factory,),
            daemon=True
        )
        self._scheduler_thread.start()
        logger.info(f"Started real-time pipeline scheduler (interval: {self.refresh_interval})")
    
    def _scheduler_loop(self, db_session_factory):
        """Background loop for scheduled updates"""
        while not self._stop_event.is_set():
            try:
                db = db_session_factory()
                try:
                    result = self.get_data(db, force_refresh=True)
                    logger.info(f"Scheduled pipeline run complete: {result.get('execution_id')}")
                finally:
                    db.close()
            except Exception as e:
                logger.error(f"Scheduled pipeline run failed: {e}")
            
            # Wait for next interval
            self._stop_event.wait(self.refresh_interval.total_seconds())
    
    def stop_scheduler(self):
        """Stop the background scheduler"""
        self._stop_event.set()
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=5)
        logger.info("Pipeline scheduler stopped")
    
    def get_status(self) -> Dict:
        """Get current pipeline status"""
        with self._lock:
            return {
                "is_running": self._is_running,
                "last_run": self._last_run.isoformat() if self._last_run else None,
                "cache_age_seconds": (datetime.utcnow() - self._last_run).total_seconds() if self._last_run else None,
                "has_cached_data": self._cache is not None,
                "refresh_interval_minutes": self.refresh_interval.total_seconds() / 60,
                "scheduler_active": self._scheduler_thread is not None and self._scheduler_thread.is_alive()
            }


# Import threading for real-time features
import threading

# Global service instances
local_pipeline_service = LocalDataPipelineService()
realtime_manager = RealtimePipelineManager(refresh_interval_minutes=5)


def get_pipeline_data(db: Session, use_cache: bool = True) -> Dict[str, Any]:
    """
    Get full pipeline data with real-time caching
    
    Args:
        db: Database session
        use_cache: If True, returns cached data if fresh (within 5 min)
                  If False, forces fresh pipeline run
    """
    return realtime_manager.get_data(db, force_refresh=not use_cache)


def export_pipeline_data_for_powerbi(db: Session, use_cache: bool = True) -> Dict[str, List[Dict]]:
    """Export pipeline data formatted for Power BI with caching"""
    pipeline_result = realtime_manager.get_data(db, force_refresh=not use_cache)
    return local_pipeline_service.export_for_powerbi(pipeline_result.get("data", {}))


def start_realtime_pipeline(db_session_factory):
    """Start real-time automatic pipeline updates"""
    realtime_manager.start_scheduler(db_session_factory)


def stop_realtime_pipeline():
    """Stop real-time pipeline updates"""
    realtime_manager.stop_scheduler()


def get_pipeline_status() -> Dict:
    """Get current real-time pipeline status"""
    return realtime_manager.get_status()
