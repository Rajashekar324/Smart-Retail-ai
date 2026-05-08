"""
🧠 AI/ML SERVICES - Internal Model Training and Scoring Service
Handles model training, scheduled retraining, anomaly scoring, clustering jobs
"""
from __future__ import annotations

from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from enum import Enum
import json
import pickle
import os
from pathlib import Path


class ModelStatus(Enum):
    TRAINING = "training"
    READY = "ready"
    FAILED = "failed"
    DEPRECATED = "deprecated"


class MLInternalService:
    """Internal ML service for model management and scheduled jobs"""
    
    def __init__(self):
        self.models_dir = Path("./models")
        self.models_dir.mkdir(parents=True, exist_ok=True)
        
        self.registered_models = {}
        self.training_jobs = []
        self.scheduled_jobs = {}
        
        self._initialize_models()
    
    def _initialize_models(self):
        """Initialize registered models"""
        self.registered_models = {
            "demand_forecast": {
                "name": "Demand Forecasting Model",
                "type": "time_series",
                "algorithm": "prophet",
                "version": "1.2.0",
                "status": ModelStatus.READY,
                "last_trained": (datetime.utcnow() - timedelta(days=1)).isoformat(),
                "metrics": {
                    "mape": 8.5,
                    "rmse": 1250.0,
                    "mae": 890.0
                },
                "features": ["day_of_week", "month", "promotions", "seasonality"],
                "retrain_schedule": "0 2 * * 0",  # Weekly on Sunday at 2 AM
                "dataset": "orders_history"
            },
            "customer_segmentation": {
                "name": "Customer Segmentation Model",
                "type": "clustering",
                "algorithm": "kmeans",
                "version": "2.1.0",
                "status": ModelStatus.READY,
                "last_trained": (datetime.utcnow() - timedelta(days=2)).isoformat(),
                "metrics": {
                    "silhouette_score": 0.68,
                    "inertia": 2450.0,
                    "clusters": 5
                },
                "features": ["order_frequency", "total_spent", "avg_order_value", "recency", "category_diversity"],
                "retrain_schedule": "0 3 * * 0",  # Weekly on Sunday at 3 AM
                "dataset": "customer_features"
            },
            "anomaly_detection": {
                "name": "Transaction Anomaly Detection",
                "type": "anomaly_detection",
                "algorithm": "isolation_forest",
                "version": "1.5.0",
                "status": ModelStatus.READY,
                "last_trained": (datetime.utcnow() - timedelta(days=1)).isoformat(),
                "metrics": {
                    "precision": 0.92,
                    "recall": 0.88,
                    "f1_score": 0.90,
                    "false_positive_rate": 0.03
                },
                "features": ["amount", "order_items_count", "time_of_day", "user_history", "payment_method"],
                "retrain_schedule": "0 1 * * 0",  # Weekly on Sunday at 1 AM
                "dataset": "transactions"
            },
            "product_recommendations": {
                "name": "Product Recommendation Model",
                "type": "recommendation",
                "algorithm": "collaborative_filtering",
                "version": "1.3.0",
                "status": ModelStatus.READY,
                "last_trained": (datetime.utcnow() - timedelta(hours=6)).isoformat(),
                "metrics": {
                    "ndcg": 0.75,
                    "map": 0.68,
                    "precision@10": 0.45,
                    "recall@10": 0.32
                },
                "features": ["user_interactions", "product_attributes", "category", "price_range"],
                "retrain_schedule": "0 */6 * * *",  # Every 6 hours
                "dataset": "user_product_interactions"
            },
            "churn_prediction": {
                "name": "Customer Churn Prediction",
                "type": "classification",
                "algorithm": "xgboost",
                "version": "1.1.0",
                "status": ModelStatus.READY,
                "last_trained": (datetime.utcnow() - timedelta(days=3)).isoformat(),
                "metrics": {
                    "accuracy": 0.89,
                    "precision": 0.85,
                    "recall": 0.82,
                    "auc_roc": 0.93
                },
                "features": ["days_since_last_order", "order_frequency", "avg_order_value", "support_tickets", "returns"],
                "retrain_schedule": "0 4 * * 0",  # Weekly on Sunday at 4 AM
                "dataset": "customer_behavior"
            }
        }
    
    # Model Training Operations
    def train_model(self, model_id: str, hyperparameters: Dict = None, 
                   validation_split: float = 0.2) -> Dict[str, Any]:
        """Train a machine learning model"""
        model_info = self.registered_models.get(model_id)
        if not model_info:
            return {"error": f"Model {model_id} not found"}
        
        job_id = f"train_{model_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        
        # Record training job
        job = {
            "job_id": job_id,
            "model_id": model_id,
            "model_name": model_info["name"],
            "status": "training",
            "start_time": datetime.utcnow().isoformat(),
            "hyperparameters": hyperparameters or {},
            "validation_split": validation_split,
            "progress": 0
        }
        
        self.training_jobs.append(job)
        
        # Simulate training process (in production, this would run actual ML training)
        try:
            # Update model status
            model_info["status"] = ModelStatus.TRAINING
            
            # Simulate training steps
            job["progress"] = 25
            # ... data loading
            job["progress"] = 50
            # ... model training
            job["progress"] = 75
            # ... validation
            job["progress"] = 100
            
            # Update model info
            model_info["status"] = ModelStatus.READY
            model_info["last_trained"] = datetime.utcnow().isoformat()
            model_info["version"] = self._increment_version(model_info["version"])
            
            # Save model artifact
            self._save_model_artifact(model_id, model_info)
            
            job["status"] = "completed"
            job["end_time"] = datetime.utcnow().isoformat()
            job["new_version"] = model_info["version"]
            
            return {
                "success": True,
                "job_id": job_id,
                "model_id": model_id,
                "new_version": model_info["version"],
                "metrics": model_info["metrics"],
                "duration_minutes": 45
            }
            
        except Exception as e:
            model_info["status"] = ModelStatus.FAILED
            job["status"] = "failed"
            job["error"] = str(e)
            return {"error": str(e)}
    
    def _increment_version(self, version: str) -> str:
        """Increment patch version number"""
        parts = version.split(".")
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    
    def _save_model_artifact(self, model_id: str, model_info: Dict):
        """Save model artifact to disk"""
        artifact_path = self.models_dir / f"{model_id}_{model_info['version']}.pkl"
        
        # In production, this would save the actual model object
        # pickle.dump(model_object, open(artifact_path, 'wb'))
        
        # For demo, save metadata
        metadata_path = self.models_dir / f"{model_id}_{model_info['version']}.json"
        with open(metadata_path, 'w') as f:
            json.dump(model_info, f, indent=2)
    
    def schedule_retraining(self, model_id: str, schedule: str = None) -> Dict[str, Any]:
        """Schedule automatic model retraining"""
        model_info = self.registered_models.get(model_id)
        if not model_info:
            return {"error": f"Model {model_id} not found"}
        
        schedule = schedule or model_info.get("retrain_schedule", "0 2 * * 0")
        
        job_config = {
            "model_id": model_id,
            "schedule": schedule,
            "enabled": True,
            "last_run": None,
            "next_run": self._calculate_next_run(schedule),
            "created_at": datetime.utcnow().isoformat()
        }
        
        self.scheduled_jobs[model_id] = job_config
        
        return {
            "success": True,
            "model_id": model_id,
            "schedule": schedule,
            "next_run": job_config["next_run"]
        }
    
    def _calculate_next_run(self, cron_schedule: str) -> str:
        """Calculate next run time from cron schedule"""
        # Simplified calculation - in production use croniter library
        parts = cron_schedule.split()
        if len(parts) == 5:
            # Cron format: minute hour day month weekday
            minute, hour, day, month, weekday = parts
            
            now = datetime.utcnow()
            next_run = now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
            
            if next_run <= now:
                next_run += timedelta(days=1)
            
            return next_run.isoformat()
        
        return (datetime.utcnow() + timedelta(days=1)).isoformat()
    
    def run_scheduled_retraining(self) -> List[Dict[str, Any]]:
        """Check and run scheduled retraining jobs"""
        results = []
        now = datetime.utcnow()
        
        for model_id, job in self.scheduled_jobs.items():
            if not job["enabled"]:
                continue
            
            next_run = datetime.fromisoformat(job["next_run"])
            if now >= next_run:
                # Run retraining
                result = self.train_model(model_id)
                
                # Update schedule
                job["last_run"] = now.isoformat()
                job["next_run"] = self._calculate_next_run(job["schedule"])
                
                results.append({
                    "model_id": model_id,
                    "result": result,
                    "next_run": job["next_run"]
                })
        
        return results
    
    # Anomaly Scoring
    def score_anomalies(self, data: List[Dict[str, Any]], 
                       model_id: str = "anomaly_detection") -> List[Dict[str, Any]]:
        """Score transactions for anomalies"""
        results = []
        
        for record in data:
            # Simulate anomaly scoring
            # In production, this would use the actual trained model
            
            score = self._calculate_anomaly_score(record)
            
            results.append({
                "record_id": record.get("id"),
                "anomaly_score": score,
                "is_anomaly": score > 0.7,
                "confidence": min(score * 100, 100),
                "features": {
                    "amount_deviation": abs(record.get("amount", 0) - 5000) / 5000,
                    "time_risk": 1 if record.get("hour", 12) < 6 else 0,
                    "velocity_risk": record.get("orders_last_hour", 0) / 10
                }
            })
        
        return results
    
    def _calculate_anomaly_score(self, record: Dict) -> float:
        """Calculate anomaly score for a record"""
        # Simplified scoring logic
        score = 0.0
        
        # Amount-based scoring
        amount = record.get("amount", 0)
        if amount > 50000:
            score += 0.4
        elif amount > 20000:
            score += 0.2
        
        # Time-based scoring
        hour = record.get("hour", 12)
        if hour < 5 or hour > 23:
            score += 0.3
        
        # Velocity-based scoring
        orders_last_hour = record.get("orders_last_hour", 0)
        if orders_last_hour > 10:
            score += 0.3
        
        return min(score, 1.0)
    
    # Clustering Operations
    def run_clustering(self, data: List[Dict[str, Any]], 
                      model_id: str = "customer_segmentation") -> Dict[str, Any]:
        """Run customer clustering job"""
        try:
            # Simulate clustering
            # In production, this would use KMeans or other clustering algorithm
            
            clusters = {
                0: {"name": "VIP Customers", "count": 0, "avg_spend": 0},
                1: {"name": "Active Shoppers", "count": 0, "avg_spend": 0},
                2: {"name": "New Customers", "count": 0, "avg_spend": 0},
                3: {"name": "At Risk", "count": 0, "avg_spend": 0},
                4: {"name": "Inactive", "count": 0, "avg_spend": 0}
            }
            
            for record in data:
                # Simple clustering logic based on features
                total_spent = record.get("total_spent", 0)
                order_count = record.get("order_count", 0)
                days_since_last = record.get("days_since_last_order", 999)
                
                if total_spent > 50000 and order_count > 20:
                    cluster_id = 0  # VIP
                elif days_since_last < 30 and order_count > 5:
                    cluster_id = 1  # Active
                elif order_count < 3:
                    cluster_id = 2  # New
                elif days_since_last > 90:
                    cluster_id = 4  # Inactive
                else:
                    cluster_id = 3  # At Risk
                
                clusters[cluster_id]["count"] += 1
                clusters[cluster_id]["avg_spend"] += total_spent
            
            # Calculate averages
            for cluster in clusters.values():
                if cluster["count"] > 0:
                    cluster["avg_spend"] = cluster["avg_spend"] / cluster["count"]
            
            return {
                "success": True,
                "model_id": model_id,
                "total_records": len(data),
                "clusters": clusters,
                "silhouette_score": 0.68
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    # Model Management
    def get_model_info(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Get model information"""
        model = self.registered_models.get(model_id)
        if not model:
            return None
        
        return {
            "id": model_id,
            "name": model["name"],
            "type": model["type"],
            "algorithm": model["algorithm"],
            "version": model["version"],
            "status": model["status"].value,
            "last_trained": model["last_trained"],
            "metrics": model["metrics"],
            "features": model["features"],
            "dataset": model["dataset"],
            "retrain_schedule": model.get("retrain_schedule")
        }
    
    def list_models(self) -> List[Dict[str, Any]]:
        """List all registered models"""
        return [
            self.get_model_info(model_id)
            for model_id in self.registered_models.keys()
        ]
    
    def get_training_jobs(self, status: str = None) -> List[Dict[str, Any]]:
        """Get training jobs"""
        jobs = self.training_jobs
        
        if status:
            jobs = [j for j in jobs if j["status"] == status]
        
        # Sort by start time (newest first)
        jobs.sort(key=lambda x: x["start_time"], reverse=True)
        
        return jobs
    
    def get_scheduled_jobs(self) -> List[Dict[str, Any]]:
        """Get scheduled retraining jobs"""
        return [
            {
                "model_id": model_id,
                **job_info
            }
            for model_id, job_info in self.scheduled_jobs.items()
        ]
    
    def delete_model_version(self, model_id: str, version: str) -> Dict[str, Any]:
        """Delete a specific model version"""
        try:
            # Remove model artifact
            artifact_path = self.models_dir / f"{model_id}_{version}.json"
            if artifact_path.exists():
                artifact_path.unlink()
            
            return {
                "success": True,
                "model_id": model_id,
                "version": version,
                "message": "Model version deleted successfully"
            }
        except Exception as e:
            return {"error": str(e)}
    
    def get_model_health(self) -> Dict[str, Any]:
        """Get overall model health status"""
        total = len(self.registered_models)
        ready = len([m for m in self.registered_models.values() if m["status"] == ModelStatus.READY])
        training = len([m for m in self.registered_models.values() if m["status"] == ModelStatus.TRAINING])
        failed = len([m for m in self.registered_models.values() if m["status"] == ModelStatus.FAILED])
        
        # Calculate average metrics
        all_metrics = [m["metrics"] for m in self.registered_models.values()]
        
        return {
            "total_models": total,
            "ready": ready,
            "training": training,
            "failed": failed,
            "health_percentage": (ready / total * 100) if total > 0 else 0,
            "scheduled_jobs": len(self.scheduled_jobs),
            "active_training_jobs": len([j for j in self.training_jobs if j["status"] == "training"]),
            "average_metrics": {
                "accuracy": sum(m.get("accuracy", 0) for m in all_metrics) / len(all_metrics) if all_metrics else 0,
                "precision": sum(m.get("precision", 0) for m in all_metrics) / len(all_metrics) if all_metrics else 0
            }
        }


ml_internal_service = MLInternalService()
