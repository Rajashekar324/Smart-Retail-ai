"""
🔄 ETL PIPELINES - Internal Data Engineering Service
Handles ADF pipelines, Databricks jobs, Spark transformations, Delta Lake
"""
from __future__ import annotations

from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from enum import Enum
import json


class PipelineStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ETLPipelineService:
    """Internal ETL pipeline orchestration service"""
    
    def __init__(self):
        self.adf_pipelines = {}
        self.databricks_jobs = {}
        self.spark_sessions = {}
        self.delta_tables = {}
        self._initialize_pipelines()
    
    def _initialize_pipelines(self):
        """Initialize default ETL pipelines"""
        # ADF Pipelines
        self.adf_pipelines = {
            "orders_etl": {
                "name": "Orders ETL Pipeline",
                "activities": [
                    {"name": "Extract_Orders", "type": "Copy", "source": "API", "sink": "Raw"},
                    {"name": "Transform_Orders", "type": "DataFlow", "source": "Raw", "sink": "Staging"},
                    {"name": "Load_Curated", "type": "Copy", "source": "Staging", "sink": "Curated"}
                ],
                "schedule": "0 */15 * * * *",  # Every 15 minutes
                "last_run": None,
                "status": PipelineStatus.PENDING
            },
            "product_sync": {
                "name": "Product Catalog Sync",
                "activities": [
                    {"name": "Extract_Products", "type": "Copy", "source": "PostgreSQL", "sink": "Raw"},
                    {"name": "Transform_Products", "type": "DataFlow", "source": "Raw", "sink": "Staging"}
                ],
                "schedule": "0 */30 * * * *",  # Every 30 minutes
                "last_run": None,
                "status": PipelineStatus.PENDING
            },
            "inventory_sync": {
                "name": "Inventory Data Sync",
                "activities": [
                    {"name": "Extract_Inventory", "type": "Copy", "source": "API", "sink": "Raw"},
                    {"name": "Merge_Delta", "type": "DataFlow", "source": "Raw", "sink": "Curated"}
                ],
                "schedule": "0 */10 * * * *",  # Every 10 minutes
                "last_run": None,
                "status": PipelineStatus.PENDING
            }
        }
        
        # Databricks Jobs
        self.databricks_jobs = {
            "customer_segmentation": {
                "name": "Customer Segmentation ML",
                "notebook_path": "/Shared/ML/customer_segmentation",
                "cluster": "ml-cluster-4x",
                "schedule": "0 2 * * *",  # Daily at 2 AM
                "tasks": [
                    {"name": "extract_features", "type": "python"},
                    {"name": "run_clustering", "type": "python"},
                    {"name": "save_results", "type": "python"}
                ],
                "libraries": ["scikit-learn", "pandas", "numpy"]
            },
            "demand_forecasting": {
                "name": "Demand Forecasting",
                "notebook_path": "/Shared/ML/demand_forecast",
                "cluster": "ml-cluster-4x",
                "schedule": "0 */6 * * *",  # Every 6 hours
                "tasks": [
                    {"name": "load_data", "type": "python"},
                    {"name": "train_models", "type": "python"},
                    {"name": "generate_predictions", "type": "python"}
                ],
                "libraries": ["prophet", "statsmodels", "tensorflow"]
            },
            "recommendations": {
                "name": "Product Recommendations",
                "notebook_path": "/Shared/ML/recommendations",
                "cluster": "ml-cluster-4x",
                "schedule": "0 4 * * *",  # Daily at 4 AM
                "tasks": [
                    {"name": "build_interaction_matrix", "type": "python"},
                    {"name": "train_collaborative_filtering", "type": "python"},
                    {"name": "generate_recommendations", "type": "python"}
                ],
                "libraries": ["surprise", "pandas", "numpy"]
            }
        }
        
        # Delta Lake Tables
        self.delta_tables = {
            "raw.orders": {
                "path": "abfss://raw@datalake.dfs.core.windows.net/orders",
                "schema": "order_schema",
                "partitioned_by": ["date"],
                "retention_days": 90
            },
            "staging.orders": {
                "path": "abfss://staging@datalake.dfs.core.windows.net/orders",
                "schema": "order_schema_cleaned",
                "partitioned_by": ["date", "status"],
                "retention_days": 60
            },
            "curated.orders": {
                "path": "abfss://curated@datalake.dfs.core.windows.net/orders",
                "schema": "order_schema_enriched",
                "partitioned_by": ["year", "month"],
                "retention_days": 365
            },
            "analytics.sales_summary": {
                "path": "abfss://analytics@datalake.dfs.core.windows.net/sales_summary",
                "schema": "sales_summary",
                "partitioned_by": ["year", "month"],
                "retention_days": 730
            }
        }
    
    # ADF Pipeline Operations
    def trigger_adf_pipeline(self, pipeline_id: str, parameters: Dict = None) -> Dict[str, Any]:
        """Trigger Azure Data Factory pipeline"""
        pipeline = self.adf_pipelines.get(pipeline_id)
        if not pipeline:
            return {"error": "Pipeline not found"}
        
        try:
            # Simulate ADF pipeline execution
            run_id = f"{pipeline_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
            
            # Update status
            pipeline["status"] = PipelineStatus.RUNNING
            pipeline["last_run"] = {
                "run_id": run_id,
                "start_time": datetime.utcnow().isoformat(),
                "status": "running",
                "parameters": parameters or {}
            }
            
            # In production, this would call ADF REST API
            # response = requests.post(
            #     f"https://management.azure.com/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.DataFactory/factories/{factory}/pipelines/{pipeline_id}/createRun",
            #     headers={"Authorization": f"Bearer {token}"},
            #     json={"parameters": parameters}
            # )
            
            return {
                "success": True,
                "run_id": run_id,
                "pipeline_id": pipeline_id,
                "status": "running",
                "message": "Pipeline triggered successfully"
            }
        except Exception as e:
            pipeline["status"] = PipelineStatus.FAILED
            return {"error": str(e)}
    
    def get_adf_pipeline_status(self, pipeline_id: str) -> Dict[str, Any]:
        """Get ADF pipeline status"""
        pipeline = self.adf_pipelines.get(pipeline_id)
        if not pipeline:
            return {"error": "Pipeline not found"}
        
        return {
            "pipeline_id": pipeline_id,
            "name": pipeline["name"],
            "status": pipeline["status"].value,
            "schedule": pipeline["schedule"],
            "activities": pipeline["activities"],
            "last_run": pipeline["last_run"]
        }
    
    def list_adf_pipelines(self) -> List[Dict[str, Any]]:
        """List all ADF pipelines"""
        return [
            {
                "id": k,
                "name": v["name"],
                "status": v["status"].value,
                "schedule": v["schedule"],
                "activities_count": len(v["activities"]),
                "last_run": v["last_run"]
            }
            for k, v in self.adf_pipelines.items()
        ]
    
    # Databricks Operations
    def submit_databricks_job(self, job_id: str, parameters: Dict = None) -> Dict[str, Any]:
        """Submit Databricks job"""
        job = self.databricks_jobs.get(job_id)
        if not job:
            return {"error": "Job not found"}
        
        try:
            run_id = f"{job_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
            
            # In production, this would call Databricks REST API
            # response = requests.post(
            #     f"{databricks_host}/api/2.1/jobs/run-now",
            #     headers={"Authorization": f"Bearer {token}"},
            #     json={"job_id": job_id, "notebook_params": parameters}
            # )
            
            return {
                "success": True,
                "run_id": run_id,
                "job_id": job_id,
                "job_name": job["name"],
                "cluster": job["cluster"],
                "status": "pending",
                "tasks": len(job["tasks"])
            }
        except Exception as e:
            return {"error": str(e)}
    
    def get_databricks_job_status(self, job_id: str) -> Dict[str, Any]:
        """Get Databricks job status"""
        job = self.databricks_jobs.get(job_id)
        if not job:
            return {"error": "Job not found"}
        
        return {
            "job_id": job_id,
            "name": job["name"],
            "cluster": job["cluster"],
            "schedule": job["schedule"],
            "tasks": job["tasks"],
            "libraries": job["libraries"]
        }
    
    # Spark Operations
    def submit_spark_job(self, job_name: str, script_path: str, 
                        args: List[str] = None) -> Dict[str, Any]:
        """Submit Spark job"""
        try:
            # Simulate Spark job submission
            job_id = f"spark_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
            
            # In production, this would use spark-submit or Databricks API
            # spark-submit --master yarn --deploy-mode cluster script.py args
            
            self.spark_sessions[job_id] = {
                "name": job_name,
                "script": script_path,
                "args": args or [],
                "status": "running",
                "start_time": datetime.utcnow().isoformat()
            }
            
            return {
                "success": True,
                "job_id": job_id,
                "name": job_name,
                "status": "running"
            }
        except Exception as e:
            return {"error": str(e)}
    
    def get_spark_job_status(self, job_id: str) -> Dict[str, Any]:
        """Get Spark job status"""
        job = self.spark_sessions.get(job_id)
        if not job:
            return {"error": "Job not found"}
        
        return {
            "job_id": job_id,
            "name": job["name"],
            "script": job["script"],
            "status": job["status"],
            "start_time": job["start_time"]
        }
    
    # Delta Lake Operations
    def delta_optimize(self, table_path: str) -> Dict[str, Any]:
        """Optimize Delta table"""
        try:
            # Simulate Delta optimize
            # In production: spark.sql(f"OPTIMIZE {table_path}")
            
            return {
                "success": True,
                "table": table_path,
                "files_compacted": 45,
                "zorder_by": ["date", "user_id"],
                "duration_seconds": 120
            }
        except Exception as e:
            return {"error": str(e)}
    
    def delta_vacuum(self, table_path: str, retention_hours: int = 168) -> Dict[str, Any]:
        """Vacuum Delta table"""
        try:
            # Simulate Delta vacuum
            # In production: spark.sql(f"VACUUM {table_path} RETAIN {retention_hours} HOURS")
            
            return {
                "success": True,
                "table": table_path,
                "files_deleted": 23,
                "space_reclaimed_gb": 1.2,
                "retention_hours": retention_hours
            }
        except Exception as e:
            return {"error": str(e)}
    
    def get_delta_table_info(self, table_path: str) -> Dict[str, Any]:
        """Get Delta table information"""
        table = self.delta_tables.get(table_path)
        if not table:
            return {"error": "Table not found"}
        
        return {
            "table": table_path,
            "path": table["path"],
            "schema": table["schema"],
            "partitioned_by": table["partitioned_by"],
            "retention_days": table["retention_days"],
            "version": 45,
            "size_gb": 2.4,
            "num_files": 120,
            "last_modified": datetime.utcnow().isoformat()
        }
    
    def get_pipeline_health(self) -> Dict[str, Any]:
        """Get overall pipeline health"""
        return {
            "adf_pipelines": {
                "total": len(self.adf_pipelines),
                "healthy": len([p for p in self.adf_pipelines.values() if p["status"] == PipelineStatus.SUCCESS]),
                "failed": len([p for p in self.adf_pipelines.values() if p["status"] == PipelineStatus.FAILED]),
                "running": len([p for p in self.adf_pipelines.values() if p["status"] == PipelineStatus.RUNNING])
            },
            "databricks_jobs": {
                "total": len(self.databricks_jobs),
                "healthy": len(self.databricks_jobs),
                "failed": 0
            },
            "spark_jobs": {
                "total": len(self.spark_sessions),
                "running": len([j for j in self.spark_sessions.values() if j["status"] == "running"])
            },
            "delta_tables": {
                "total": len(self.delta_tables),
                "optimized_today": 3,
                "vacuumed_today": 2
            }
        }
    
    def run_full_etl(self) -> Dict[str, Any]:
        """Run full ETL pipeline"""
        results = {
            "start_time": datetime.utcnow().isoformat(),
            "pipelines_triggered": [],
            "errors": [],
            "status": "running"
        }
        
        try:
            # Trigger ADF pipelines
            for pipeline_id in self.adf_pipelines:
                result = self.trigger_adf_pipeline(pipeline_id)
                if "error" in result:
                    results["errors"].append({"pipeline": pipeline_id, "error": result["error"]})
                else:
                    results["pipelines_triggered"].append(pipeline_id)
            
            # Submit Databricks jobs
            for job_id in self.databricks_jobs:
                result = self.submit_databricks_job(job_id)
                if "error" in result:
                    results["errors"].append({"job": job_id, "error": result["error"]})
                else:
                    results["pipelines_triggered"].append(job_id)
            
            results["status"] = "completed" if not results["errors"] else "partial_failure"
            
        except Exception as e:
            results["status"] = "failed"
            results["errors"].append({"system": str(e)})
        
        results["end_time"] = datetime.utcnow().isoformat()
        return results


etl_pipeline_service = ETLPipelineService()
