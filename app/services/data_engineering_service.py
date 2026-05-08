from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import json


class DataEngineeringService:
    """Data engineering pipeline monitoring service"""
    
    def __init__(self):
        self.pipelines = {
            "orders_etl": {
                "name": "Orders ETL",
                "description": "Extract, transform and load order data",
                "type": "adf",
                "schedule": "Every 15 minutes",
                "layers": ["raw", "staging", "curated"]
            },
            "user_analytics": {
                "name": "User Analytics Pipeline",
                "description": "Process user behavior and analytics",
                "type": "databricks",
                "schedule": "Hourly",
                "layers": ["raw", "staging", "curated", "analytics"]
            },
            "product_catalog": {
                "name": "Product Catalog Sync",
                "description": "Sync product data from various sources",
                "type": "adf",
                "schedule": "Every 30 minutes",
                "layers": ["raw", "staging", "curated"]
            },
            "inventory_sync": {
                "name": "Inventory Data Sync",
                "description": "Sync inventory levels across warehouses",
                "type": "pyspark",
                "schedule": "Every 10 minutes",
                "layers": ["raw", "curated"]
            },
            "customer_segmentation": {
                "name": "Customer Segmentation",
                "description": "ML pipeline for customer clustering",
                "type": "databricks",
                "schedule": "Daily",
                "layers": ["staging", "curated", "ml_features"]
            },
            "recommendations": {
                "name": "Product Recommendations",
                "description": "Generate product recommendations",
                "type": "databricks",
                "schedule": "Every 6 hours",
                "layers": ["staging", "curated", "ml_features"]
            }
        }
        
        self._generate_simulated_runs()
    
    def _generate_simulated_runs(self):
        """Generate simulated pipeline runs"""
        self.pipeline_runs = []
        
        for pipeline_id, pipeline in self.pipelines.items():
            # Generate runs for last 24 hours
            for i in range(10):
                run_time = datetime.utcnow() - timedelta(hours=i*2.4)
                
                # Simulate different statuses
                if i == 0 and pipeline_id == "inventory_sync":
                    status = "running"
                elif i == 1 and pipeline_id == "customer_segmentation":
                    status = "failed"
                else:
                    status = "success"
                
                run = {
                    "run_id": f"{pipeline_id}_{run_time.strftime('%Y%m%d%H%M%S')}",
                    "pipeline_id": pipeline_id,
                    "pipeline_name": pipeline["name"],
                    "type": pipeline["type"],
                    "status": status,
                    "start_time": run_time.isoformat(),
                    "end_time": (run_time + timedelta(minutes=5 if status != "running" else 0)).isoformat() if status != "running" else None,
                    "duration_minutes": 3.5 if status != "running" else None,
                    "records_processed": 15000 + (i * 1000),
                    "error_message": "Connection timeout" if status == "failed" else None
                }
                self.pipeline_runs.append(run)
        
        # Sort by start time
        self.pipeline_runs.sort(key=lambda x: x["start_time"], reverse=True)
    
    def get_pipeline_status(self) -> Dict[str, Any]:
        """Get status of all data pipelines"""
        pipelines_status = []
        
        for pipeline_id, pipeline in self.pipelines.items():
            # Get last run
            last_run = next((r for r in self.pipeline_runs if r["pipeline_id"] == pipeline_id), None)
            
            # Get success rate
            pipeline_runs = [r for r in self.pipeline_runs if r["pipeline_id"] == pipeline_id]
            success_count = len([r for r in pipeline_runs if r["status"] == "success"])
            success_rate = (success_count / len(pipeline_runs) * 100) if pipeline_runs else 0
            
            pipelines_status.append({
                "id": pipeline_id,
                "name": pipeline["name"],
                "description": pipeline["description"],
                "type": pipeline["type"],
                "schedule": pipeline["schedule"],
                "status": last_run["status"] if last_run else "unknown",
                "last_run": last_run["start_time"] if last_run else None,
                "success_rate": round(success_rate, 1),
                "total_runs": len(pipeline_runs),
                "layers": pipeline["layers"]
            })
        
        return {
            "pipelines": pipelines_status,
            "total_pipelines": len(pipelines_status),
            "running": len([p for p in pipelines_status if p["status"] == "running"]),
            "failed_last_24h": len([p for p in pipelines_status if p["status"] == "failed"]),
            "last_updated": datetime.utcnow().isoformat()
        }
    
    def get_pipeline_runs(self, pipeline_id: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get pipeline run history"""
        runs = self.pipeline_runs
        
        if pipeline_id:
            runs = [r for r in runs if r["pipeline_id"] == pipeline_id]
        
        return runs[:limit]
    
    def get_data_flow_status(self) -> Dict[str, Any]:
        """Get data flow status across raw/staging/curated layers"""
        return {
            "layers": {
                "raw": {
                    "name": "Raw Data",
                    "description": "Unprocessed data from sources",
                    "status": "healthy",
                    "tables": 15,
                    "records": 2845000,
                    "size_gb": 12.4,
                    "last_ingestion": (datetime.utcnow() - timedelta(minutes=10)).isoformat()
                },
                "staging": {
                    "name": "Staging",
                    "description": "Cleaned and validated data",
                    "status": "healthy",
                    "tables": 12,
                    "records": 2800000,
                    "size_gb": 9.8,
                    "last_update": (datetime.utcnow() - timedelta(minutes=15)).isoformat()
                },
                "curated": {
                    "name": "Curated",
                    "description": "Business-ready data",
                    "status": "healthy",
                    "tables": 8,
                    "records": 1250000,
                    "size_gb": 6.2,
                    "last_update": (datetime.utcnow() - timedelta(minutes=20)).isoformat()
                },
                "analytics": {
                    "name": "Analytics",
                    "description": "Aggregated analytics data",
                    "status": "healthy",
                    "tables": 6,
                    "records": 45000,
                    "size_gb": 1.8,
                    "last_update": (datetime.utcnow() - timedelta(hours=1)).isoformat()
                },
                "ml_features": {
                    "name": "ML Features",
                    "description": "Machine learning feature store",
                    "status": "healthy",
                    "tables": 10,
                    "records": 890000,
                    "size_gb": 3.4,
                    "last_update": (datetime.utcnow() - timedelta(hours=6)).isoformat()
                }
            },
            "data_quality": {
                "overall_score": 96.5,
                "completeness": 98.2,
                "accuracy": 95.8,
                "timeliness": 97.5
            }
        }
    
    def get_ingestion_jobs(self) -> List[Dict[str, Any]]:
        """Get data ingestion jobs status"""
        return [
            {
                "name": "Orders API Ingestion",
                "source": "REST API",
                "destination": "raw.orders",
                "status": "running",
                "records_per_min": 450,
                "latency_seconds": 2.3,
                "last_record": datetime.utcnow().isoformat()
            },
            {
                "name": "Product Catalog Sync",
                "source": "PostgreSQL",
                "destination": "raw.products",
                "status": "success",
                "records_per_min": 120,
                "latency_seconds": 5.1,
                "last_record": (datetime.utcnow() - timedelta(minutes=5)).isoformat()
            },
            {
                "name": "User Events Stream",
                "source": "Kafka",
                "destination": "raw.events",
                "status": "running",
                "records_per_min": 2300,
                "latency_seconds": 0.8,
                "last_record": datetime.utcnow().isoformat()
            },
            {
                "name": "Inventory CSV Upload",
                "source": "Blob Storage",
                "destination": "raw.inventory",
                "status": "scheduled",
                "next_run": (datetime.utcnow() + timedelta(minutes=30)).isoformat()
            }
        ]
    
    def get_databricks_runs(self) -> List[Dict[str, Any]]:
        """Get Databricks job runs"""
        return [
            {
                "run_id": "db-2024-001",
                "job_name": "Customer Segmentation",
                "cluster": "ml-cluster-4x",
                "status": "success",
                "start_time": (datetime.utcnow() - timedelta(hours=2)).isoformat(),
                "duration_minutes": 45,
                "tasks": [
                    {"name": "data_prep", "duration": 8, "status": "success"},
                    {"name": "feature_engineering", "duration": 15, "status": "success"},
                    {"name": "clustering", "duration": 18, "status": "success"},
                    {"name": "save_results", "duration": 4, "status": "success"}
                ],
                "output_rows": 45000
            },
            {
                "run_id": "db-2024-002",
                "job_name": "Product Recommendations",
                "cluster": "ml-cluster-4x",
                "status": "success",
                "start_time": (datetime.utcnow() - timedelta(hours=4)).isoformat(),
                "duration_minutes": 32,
                "tasks": [
                    {"name": "load_interactions", "duration": 5, "status": "success"},
                    {"name": "train_model", "duration": 22, "status": "success"},
                    {"name": "generate_recommendations", "duration": 5, "status": "success"}
                ],
                "output_rows": 89000
            },
            {
                "run_id": "db-2024-003",
                "job_name": "User Analytics",
                "cluster": "analytics-cluster-2x",
                "status": "running",
                "start_time": (datetime.utcnow() - timedelta(minutes=15)).isoformat(),
                "duration_minutes": None,
                "tasks": [
                    {"name": "extract_data", "duration": 5, "status": "success"},
                    {"name": "aggregate_metrics", "duration": 8, "status": "running"},
                    {"name": "update_dashboards", "duration": None, "status": "pending"}
                ],
                "output_rows": None
            }
        ]
    
    def get_adf_pipelines(self) -> List[Dict[str, Any]]:
        """Get Azure Data Factory pipeline status"""
        return [
            {
                "name": "Orders_ETL",
                "folder": "Production",
                "status": "success",
                "last_run": (datetime.utcnow() - timedelta(minutes=12)).isoformat(),
                "duration": "4m 32s",
                "activities": 8,
                "data_read_gb": 0.8,
                "data_written_gb": 0.6
            },
            {
                "name": "Product_Catalog_Sync",
                "folder": "Production",
                "status": "success",
                "last_run": (datetime.utcnow() - timedelta(minutes=25)).isoformat(),
                "duration": "2m 18s",
                "activities": 5,
                "data_read_gb": 0.3,
                "data_written_gb": 0.2
            },
            {
                "name": "Inventory_Data_Load",
                "folder": "Production",
                "status": "running",
                "last_run": datetime.utcnow().isoformat(),
                "duration": "1m 45s",
                "activities": 6,
                "data_read_gb": 0.2,
                "data_written_gb": 0.15
            },
            {
                "name": "User_Behavior_Copy",
                "folder": "Analytics",
                "status": "success",
                "last_run": (datetime.utcnow() - timedelta(hours=1)).isoformat(),
                "duration": "8m 12s",
                "activities": 4,
                "data_read_gb": 2.4,
                "data_written_gb": 1.8
            }
        ]
    
    def get_job_statistics(self) -> Dict[str, Any]:
        """Get job execution statistics"""
        return {
            "period": "Last 24 Hours",
            "total_jobs": 48,
            "successful": 45,
            "failed": 2,
            "running": 1,
            "avg_duration_min": 12.5,
            "total_records_processed": 12500000,
            "avg_throughput_per_min": 45600,
            "success_rate": 93.8,
            "trend": [
                {"hour": "00:00", "jobs": 2, "success": 2},
                {"hour": "04:00", "jobs": 3, "success": 3},
                {"hour": "08:00", "jobs": 8, "success": 7},
                {"hour": "12:00", "jobs": 12, "success": 11},
                {"hour": "16:00", "jobs": 10, "success": 9},
                {"hour": "20:00", "jobs": 8, "success": 8},
                {"hour": "Now", "jobs": 5, "success": 4}
            ]
        }
    
    def get_comprehensive_dashboard(self) -> Dict[str, Any]:
        """Get comprehensive data engineering dashboard"""
        return {
            "pipeline_status": self.get_pipeline_status(),
            "pipeline_runs": self.get_pipeline_runs(limit=20),
            "data_flow": self.get_data_flow_status(),
            "ingestion_jobs": self.get_ingestion_jobs(),
            "databricks_runs": self.get_databricks_runs(),
            "adf_pipelines": self.get_adf_pipelines(),
            "job_statistics": self.get_job_statistics()
        }


data_engineering_service = DataEngineeringService()
