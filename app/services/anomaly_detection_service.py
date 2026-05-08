from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import Order, User, OrderItem


class AnomalyDetectionService:
    """Anomaly detection service for fraud and unusual patterns"""
    
    def __init__(self):
        pass
    
    def detect_anomalies_isolation_forest(self, db: Session) -> List[Dict[str, Any]]:
        """Detect anomalies using Isolation Forest"""
        try:
            from sklearn.ensemble import IsolationForest
            
            # Get order data
            orders = db.query(Order).all()
            
            if not orders or len(orders) < 10:
                return []
            
            # Prepare features
            features = []
            order_ids = []
            
            for order in orders:
                features.append([
                    float(order.total_amount),
                    len(order.items),
                    order.created_at.hour,
                    order.created_at.weekday(),
                    1 if order.status == "Cancelled" else 0
                ])
                order_ids.append(order.id)
            
            # Simple scaling without numpy/sklearn
            # Calculate mean and std for each feature
            num_features = len(features[0])
            means = []
            stds = []
            
            for i in range(num_features):
                col_values = [f[i] for f in features]
                mean = sum(col_values) / len(col_values)
                variance = sum((x - mean) ** 2 for x in col_values) / len(col_values)
                std = variance ** 0.5
                means.append(mean)
                stds.append(std if std > 0 else 1)
            
            # Scale features manually
            features_scaled = []
            for f in features:
                scaled = [(f[i] - means[i]) / stds[i] for i in range(num_features)]
                features_scaled.append(scaled)
            
            # Train Isolation Forest
            clf = IsolationForest(contamination=0.1, random_state=42)
            predictions = clf.fit_predict(features_scaled)
            
            # Get anomalies
            anomalies = []
            for i, pred in enumerate(predictions):
                if pred == -1:
                    order = db.query(Order).filter(Order.id == order_ids[i]).first()
                    anomalies.append({
                        "order_id": order.order_number,
                        "order_id_db": order.id,
                        "type": "isolation_forest",
                        "severity": "high",
                        "reason": "Unusual pattern detected",
                        "amount": order.total_amount,
                        "items_count": len(order.items),
                        "created_at": order.created_at.isoformat(),
                        "status": order.status
                    })
            
            return anomalies
        except ImportError:
            # sklearn not available, return empty list
            return []
        except Exception as e:
            print(f"Isolation Forest error: {e}")
            return []
    
    def detect_anomalies_zscore(self, db: Session) -> List[Dict[str, Any]]:
        """Detect anomalies using Z-score analysis"""
        orders = db.query(Order).all()
        
        if not orders or len(orders) < 10:
            return []
        
        # Calculate Z-scores for order amounts without numpy
        amounts = [order.total_amount for order in orders]
        mean = sum(amounts) / len(amounts)
        variance = sum((x - mean) ** 2 for x in amounts) / len(amounts)
        std = variance ** 0.5
        
        anomalies = []
        for order in orders:
            z_score = abs((order.total_amount - mean) / std) if std > 0 else 0
            
            if z_score > 3:  # 3 standard deviations
                anomalies.append({
                    "order_id": order.order_number,
                    "order_id_db": order.id,
                    "type": "zscore",
                    "severity": "high" if z_score > 4 else "medium",
                    "reason": f"Amount {z_score:.1f} standard deviations from mean",
                    "amount": order.total_amount,
                    "items_count": len(order.items),
                    "z_score": round(z_score, 2),
                    "created_at": order.created_at.isoformat(),
                    "status": order.status
                })
        
        return anomalies
    
    def detect_anomalies_simple(self, db: Session) -> List[Dict[str, Any]]:
        """Simple rule-based anomaly detection"""
        anomalies = []
        
        # Get recent orders
        recent_orders = db.query(Order).filter(
            Order.created_at >= datetime.utcnow() - timedelta(days=7)
        ).all()
        
        # Calculate average order amount
        avg_amount = db.query(func.avg(Order.total_amount)).scalar() or 0
        
        for order in recent_orders:
            reasons = []
            severity = "low"
            
            # High value orders
            if order.total_amount > avg_amount * 5:
                reasons.append("Unusually high order value")
                severity = "high"
            
            # Many items
            if len(order.items) > 20:
                reasons.append("Unusually high item count")
                severity = "medium"
            
            # Quick cancellation
            if order.status == "Cancelled":
                time_diff = (datetime.utcnow() - order.created_at).total_seconds()
                if time_diff < 300:  # 5 minutes
                    reasons.append("Cancelled within 5 minutes")
                    severity = "high"
            
            # Unusual timing
            hour = order.created_at.hour
            if hour < 4 or hour > 23:
                reasons.append("Unusual order timing")
                severity = "medium"
            
            if reasons:
                anomalies.append({
                    "order_id": order.order_number,
                    "order_id_db": order.id,
                    "type": "rule_based",
                    "severity": severity,
                    "reason": ", ".join(reasons),
                    "amount": order.total_amount,
                    "items_count": len(order.items),
                    "created_at": order.created_at.isoformat(),
                    "status": order.status
                })
        
        return anomalies
    
    def detect_user_anomalies(self, db: Session) -> List[Dict[str, Any]]:
        """Detect suspicious user behavior"""
        anomalies = []
        
        # Get users with many recent orders
        recent_time = datetime.utcnow() - timedelta(hours=1)
        suspicious_users = db.query(
            Order.user_id,
            func.count(Order.id).label('order_count'),
            func.sum(Order.total_amount).label('total_spent')
        ).filter(
            Order.created_at >= recent_time
        ).group_by(Order.user_id).having(
            func.count(Order.id) > 5
        ).all()
        
        for user_data in suspicious_users:
            user = db.query(User).filter(User.id == user_data.user_id).first()
            anomalies.append({
                "type": "user_behavior",
                "user_id": user.id,
                "user_email": user.email,
                "severity": "high",
                "reason": f"{user_data.order_count} orders in last hour",
                "total_spent": float(user_data.total_spent),
                "order_count": user_data.order_count
            })
        
        return anomalies
    
    def get_anomaly_heatmap_data(self, db: Session) -> Dict[str, Any]:
        """Get data for anomaly heatmap visualization"""
        # Get orders by hour and day
        heatmap_data = {}
        
        for day in range(7):
            heatmap_data[day] = {}
            for hour in range(24):
                heatmap_data[day][hour] = 0
        
        orders = db.query(Order).filter(
            Order.created_at >= datetime.utcnow() - timedelta(days=30)
        ).all()
        
        for order in orders:
            day = order.created_at.weekday()
            hour = order.created_at.hour
            heatmap_data[day][hour] += 1
        
        return heatmap_data
    
    def get_fraud_metrics(self, db: Session) -> Dict[str, Any]:
        """Get fraud detection metrics"""
        total_orders = db.query(Order).count()
        cancelled_orders = db.query(Order).filter(Order.status == "Cancelled").count()
        anomaly_count = len(self.detect_anomalies_simple(db))
        
        return {
            "total_orders": total_orders,
            "cancelled_orders": cancelled_orders,
            "cancellation_rate": round((cancelled_orders / total_orders * 100), 2) if total_orders > 0 else 0,
            "detected_anomalies": anomaly_count,
            "fraud_rate": round((anomaly_count / total_orders * 100), 2) if total_orders > 0 else 0
        }
    
    def get_live_anomaly_feed(self, db: Session, limit: int = 20) -> List[Dict[str, Any]]:
        """Get live feed of recent anomalies"""
        all_anomalies = []
        
        # Get anomalies from different methods
        isolation_anomalies = self.detect_anomalies_isolation_forest(db)
        zscore_anomalies = self.detect_anomalies_zscore(db)
        user_anomalies = self.detect_user_anomalies(db)
        
        all_anomalies.extend(isolation_anomalies)
        all_anomalies.extend(zscore_anomalies)
        
        # Add timestamp for sorting
        for anomaly in all_anomalies:
            anomaly['timestamp'] = anomaly.get('created_at', datetime.utcnow().isoformat())
        
        # Sort by timestamp and limit
        all_anomalies.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return all_anomalies[:limit]
    
    def mark_as_fraud(self, order_id: int, db: Session) -> bool:
        """Mark an order as fraudulent"""
        order = db.query(Order).filter(Order.id == order_id).first()
        if order:
            order.status = "Fraud"
            db.commit()
            return True
        return False
    
    def get_comprehensive_anomaly_report(self, db: Session) -> Dict[str, Any]:
        """Get comprehensive anomaly detection report"""
        return {
            "anomalies": self.get_live_anomaly_feed(db),
            "heatmap_data": self.get_anomaly_heatmap_data(db),
            "fraud_metrics": self.get_fraud_metrics(db),
            "user_anomalies": self.detect_user_anomalies(db)
        }


anomaly_detection_service = AnomalyDetectionService()
