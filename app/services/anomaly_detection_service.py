from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from app.models import Order, User, OrderItem


class AnomalyDetectionService:
    """Real-time Anomaly detection service for fraud and unusual patterns with ML"""
    
    def __init__(self):
        self._cache = {}
        self._cache_timestamp = None
        self._cache_ttl = 30  # Cache for 30 seconds
    
    def _get_cached_or_compute(self, db: Session, key: str, compute_func) -> Any:
        """Get cached result or compute fresh"""
        now = datetime.utcnow()
        if (self._cache_timestamp and 
            (now - self._cache_timestamp).seconds < self._cache_ttl and
            key in self._cache):
            return self._cache[key]
        
        result = compute_func(db)
        self._cache[key] = result
        self._cache_timestamp = now
        return result
    
    def _calculate_fraud_risk_score(self, order: Order, avg_amount: float, 
                                   std_amount: float, user_order_history: int) -> Tuple[float, List[str]]:
        """Calculate fraud risk score (0-100) and return reasons"""
        score = 0.0
        reasons = []
        
        # 1. Amount anomaly (up to 40 points)
        if std_amount > 0:
            z_score = abs((order.total_amount - avg_amount) / std_amount)
            if z_score > 4:
                score += 40
                reasons.append(f"Amount {z_score:.1f}σ above normal (₹{order.total_amount:,.0f})")
            elif z_score > 3:
                score += 30
                reasons.append(f"Amount {z_score:.1f}σ above normal (₹{order.total_amount:,.0f})")
            elif z_score > 2:
                score += 15
                reasons.append(f"Amount {z_score:.1f}σ above normal")
        
        if order.total_amount > avg_amount * 10:
            score += 35
            reasons.append(f"Extremely high value order (₹{order.total_amount:,.0f})")
        elif order.total_amount > avg_amount * 5:
            score += 25
            reasons.append(f"High value order (₹{order.total_amount:,.0f})")
        
        # 2. Velocity check - rapid orders (up to 25 points)
        recent_orders = Order.query.filter(
            Order.user_id == order.user_id,
            Order.created_at >= datetime.utcnow() - timedelta(hours=1)
        ).count()
        
        if recent_orders > 10:
            score += 25
            reasons.append(f"{recent_orders} orders in last hour - possible bot activity")
        elif recent_orders > 5:
            score += 15
            reasons.append(f"{recent_orders} orders in last hour - unusual velocity")
        
        # 3. Item count anomaly (up to 15 points)
        item_count = len(order.items) if order.items else 0
        if item_count > 50:
            score += 15
            reasons.append(f"Abnormal item count: {item_count} items")
        elif item_count > 20:
            score += 8
            reasons.append(f"High item count: {item_count} items")
        
        # 4. Time-based anomalies (up to 10 points)
        hour = order.created_at.hour
        if hour < 5:  # Late night orders
            score += 10
            reasons.append(f"Unusual time: {hour}:00 AM order")
        
        # 5. User history (up to 10 points)
        if user_order_history == 0:
            score += 10
            reasons.append("First-time customer")
        elif user_order_history < 3:
            score += 5
            reasons.append("New customer (< 3 orders)")
        
        # 6. Cancellation pattern (up to 20 points)
        if order.status == "Cancelled":
            time_diff = (datetime.utcnow() - order.created_at).total_seconds()
            if time_diff < 60:
                score += 20
                reasons.append("Cancelled within 1 minute - possible test transaction")
            elif time_diff < 300:
                score += 15
                reasons.append("Cancelled within 5 minutes")
        
        # Check user's cancellation rate
        user_orders = db.query(Order).filter(Order.user_id == order.user_id).count()
        user_cancellations = db.query(Order).filter(
            Order.user_id == order.user_id,
            Order.status == "Cancelled"
        ).count()
        
        if user_orders > 0:
            cancel_rate = user_cancellations / user_orders
            if cancel_rate > 0.5:
                score += 15
                reasons.append(f"High cancellation rate: {cancel_rate*100:.0f}%")
        
        return min(score, 100), reasons
    
    def detect_anomalies_ml(self, db: Session) -> List[Dict[str, Any]]:
        """ML-based anomaly detection using Isolation Forest with detailed reasoning"""
        try:
            from sklearn.ensemble import IsolationForest
            
            # Get last 30 days of orders for ML training
            cutoff_date = datetime.utcnow() - timedelta(days=30)
            orders = db.query(Order).filter(Order.created_at >= cutoff_date).all()
            
            if not orders or len(orders) < 3:
                return []
            
            # Calculate statistics
            amounts = [o.total_amount for o in orders]
            avg_amount = sum(amounts) / len(amounts)
            std_amount = (sum((x - avg_amount) ** 2 for x in amounts) / len(amounts)) ** 0.5
            
            # Prepare features for ML
            features = []
            order_data = []
            
            for order in orders:
                # Get user order history
                user_history = db.query(Order).filter(
                    Order.user_id == order.user_id,
                    Order.created_at < order.created_at
                ).count()
                
                item_count = len(order.items) if order.items else 0
                
                features.append([
                    float(order.total_amount),
                    item_count,
                    order.created_at.hour,
                    order.created_at.weekday(),
                    1 if order.status == "Cancelled" else 0,
                    user_history
                ])
                order_data.append(order)
            
            # Scale features
            num_features = len(features[0])
            means = [sum(f[i] for f in features) / len(features) for i in range(num_features)]
            stds = []
            for i in range(num_features):
                variance = sum((f[i] - means[i]) ** 2 for f in features) / len(features)
                stds.append(variance ** 0.5 if variance > 0 else 1)
            
            features_scaled = [[(f[i] - means[i]) / stds[i] for i in range(num_features)] 
                              for f in features]
            
            # Train Isolation Forest
            clf = IsolationForest(contamination=0.05, random_state=42, n_estimators=100)
            predictions = clf.fit_predict(features_scaled)
            
            # Get anomalies with detailed reasoning
            anomalies = []
            for i, pred in enumerate(predictions):
                if pred == -1:  # Anomaly detected
                    order = order_data[i]
                    user_history = db.query(Order).filter(
                        Order.user_id == order.user_id,
                        Order.created_at < order.created_at
                    ).count()
                    
                    risk_score, reasons = self._calculate_fraud_risk_score(
                        order, avg_amount, std_amount, user_history
                    )
                    
                    # Determine severity based on risk score
                    if risk_score >= 70:
                        severity = "critical"
                    elif risk_score >= 50:
                        severity = "high"
                    elif risk_score >= 30:
                        severity = "medium"
                    else:
                        severity = "low"
                    
                    anomalies.append({
                        "order_id": order.order_number,
                        "order_id_db": order.id,
                        "type": "ml_isolation_forest",
                        "severity": severity,
                        "risk_score": round(risk_score, 1),
                        "reason": "; ".join(reasons) if reasons else "ML detected unusual pattern",
                        "reasons": reasons,
                        "amount": order.total_amount,
                        "items_count": len(order.items) if order.items else 0,
                        "user_id": order.user_id,
                        "user_history": user_history,
                        "created_at": order.created_at.isoformat(),
                        "status": order.status,
                        "hour": order.created_at.hour,
                        "detection_method": "ML Isolation Forest"
                    })
            
            return sorted(anomalies, key=lambda x: x['risk_score'], reverse=True)
            
        except ImportError:
            return []
        except Exception as e:
            print(f"ML Anomaly detection error: {e}")
            return []
    
    def detect_anomalies_statistical(self, db: Session) -> List[Dict[str, Any]]:
        """Statistical anomaly detection with Z-score and IQR methods - provides detailed reasoning"""
        # Use all orders for small datasets, last 30 days for larger ones
        total_orders = db.query(Order).count()
        if total_orders < 30:
            orders = db.query(Order).all()  # Use all orders for small datasets
        else:
            cutoff_date = datetime.utcnow() - timedelta(days=30)
            orders = db.query(Order).filter(Order.created_at >= cutoff_date).all()
        
        if not orders or len(orders) < 3:
            return []
        
        # Calculate statistics
        amounts = [o.total_amount for o in orders]
        sorted_amounts = sorted(amounts)
        n = len(sorted_amounts)
        
        mean = sum(amounts) / len(amounts)
        variance = sum((x - mean) ** 2 for x in amounts) / len(amounts)
        std = variance ** 0.5
        
        # IQR calculation
        q1_idx = int(n * 0.25)
        q3_idx = int(n * 0.75)
        q1 = sorted_amounts[q1_idx]
        q3 = sorted_amounts[q3_idx]
        iqr = q3 - q1
        
        anomalies = []
        
        for order in orders:
            reasons = []
            risk_score = 0
            
            # Z-score analysis - adaptive thresholds based on sample size
            if std > 0:
                z_score = (order.total_amount - mean) / std
                
                # Adaptive thresholds: stricter for large samples, looser for small
                critical_threshold = 2.5 if n > 50 else 1.8 if n > 20 else 1.2
                warning_threshold = 1.8 if n > 50 else 1.2 if n > 20 else 0.8
                
                if abs(z_score) > critical_threshold:
                    risk_score += 35
                    deviation_pct = abs((order.total_amount - mean) / mean * 100) if mean > 0 else 0
                    if z_score > 0:
                        reasons.append(f"HIGH VALUE: ₹{order.total_amount:,.0f} is {z_score:.1f}σ above average (₹{mean:,.0f})")
                        reasons.append(f"This is {deviation_pct:.0f}% higher than typical - check for price manipulation")
                    else:
                        reasons.append(f"LOW VALUE: ₹{order.total_amount:,.0f} is {abs(z_score):.1f}σ below average")
                        reasons.append(f"Unusually low value may indicate testing or error")
                elif abs(z_score) > warning_threshold:
                    risk_score += 25
                    if z_score > 0:
                        reasons.append(f"Elevated value: ₹{order.total_amount:,.0f} ({z_score:.1f}σ above mean)")
            
            # IQR outlier detection - more robust than Z-score for skewed data
            upper_fence = q3 + 1.5 * iqr
            lower_fence = q1 - 1.5 * iqr
            
            if order.total_amount > upper_fence:
                risk_score += 25
                reasons.append(f"Order exceeds upper outlier threshold of ₹{upper_fence:,.0f}")
                reasons.append(f"Only {(sum(1 for a in amounts if a > upper_fence) / len(amounts) * 100):.1f}% of orders are this high")
            elif order.total_amount < lower_fence:
                risk_score += 20
                reasons.append(f"Order below lower outlier threshold of ₹{lower_fence:,.0f}")
            
            # Multiplier-based detection for intuitive understanding
            if mean > 0:
                if order.total_amount > mean * 5:
                    risk_score += 15
                    reasons.append(f"Order value is {order.total_amount/mean:.1f}x the average - extremely high value transaction")
                elif order.total_amount > mean * 3:
                    risk_score += 10
                    reasons.append(f"Order value is {order.total_amount/mean:.1f}x the typical order amount")
            
            # Add anomaly if any reasons found
            if reasons:
                severity = "critical" if risk_score >= 70 else "high" if risk_score >= 50 else "medium" if risk_score >= 30 else "low"
                
                anomalies.append({
                    "order_id": order.order_number,
                    "order_id_db": order.id,
                    "type": "statistical",
                    "severity": severity,
                    "risk_score": round(risk_score, 1),
                    "reason": reasons[0],  # Primary reason
                    "reasons": reasons,  # All reasons
                    "amount": order.total_amount,
                    "z_score": round(z_score, 2) if std > 0 else 0,
                    "stats": {
                        "mean": round(mean, 2),
                        "std": round(std, 2),
                        "q1": round(q1, 2),
                        "q3": round(q3, 2),
                        "median": sorted_amounts[n // 2],
                        "sample_size": n
                    },
                    "user_id": order.user_id,
                    "created_at": order.created_at.isoformat(),
                    "status": order.status,
                    "detection_method": "Statistical Analysis",
                    "explanation": f"This order deviates significantly from normal patterns. Based on {n} recent orders, typical values range ₹{q1:,.0f} - ₹{q3:,.0f}."
                })
        
        return sorted(anomalies, key=lambda x: x['risk_score'], reverse=True)
    
    def detect_velocity_anomalies(self, db: Session) -> List[Dict[str, Any]]:
        """Detect velocity-based anomalies with detailed behavioral analysis"""
        anomalies = []
        now = datetime.utcnow()
        
        # Check for burst orders in short time windows
        time_windows = [
            ("5 minutes", timedelta(minutes=5), 3),
            ("15 minutes", timedelta(minutes=15), 5),
            ("1 hour", timedelta(hours=1), 10),
            ("24 hours", timedelta(hours=24), 30)
        ]
        
        for window_name, window_delta, threshold in time_windows:
            window_start = now - window_delta
            
            # Find users with many orders in this window
            suspicious_users = db.query(
                Order.user_id,
                func.count(Order.id).label('order_count'),
                func.sum(Order.total_amount).label('total_spent'),
                func.min(Order.created_at).label('first_order'),
                func.max(Order.created_at).label('last_order')
            ).filter(
                Order.created_at >= window_start
            ).group_by(Order.user_id).having(
                func.count(Order.id) >= threshold
            ).all()
            
            for user_data in suspicious_users:
                user = db.query(User).filter(User.id == user_data.user_id).first()
                if not user:
                    continue
                
                # Calculate time span
                time_span = user_data.last_order - user_data.first_order
                minutes_span = max(time_span.total_seconds() / 60, 1)  # Avoid division by zero
                
                reasons = []
                risk_score = min(user_data.order_count * 3, 60)
                
                # Primary reason
                reasons.append(f"User placed {user_data.order_count} orders within {window_name}")
                
                # Velocity analysis
                rate = user_data.order_count / minutes_span
                if rate > 2:
                    risk_score += 20
                    reasons.append(f"Bot-like activity detected: {rate:.1f} orders per minute")
                    reasons.append("Pattern suggests automated ordering system or script")
                elif rate > 1:
                    risk_score += 10
                    reasons.append(f"Unusually fast ordering: {rate:.1f} orders per minute")
                
                # Financial impact analysis
                if user_data.total_spent > 50000:
                    risk_score += 25
                    reasons.append(f"High-value burst activity: ₹{user_data.total_spent:,.0f} spent in {window_name}")
                    reasons.append("Rapid high-value transactions may indicate stolen payment method testing")
                elif user_data.total_spent > 20000:
                    risk_score += 15
                    reasons.append(f"Significant spending: ₹{user_data.total_spent:,.0f} in short period")
                
                # Pattern analysis
                if user_data.order_count > threshold * 2:
                    reasons.append(f"Activity level is {user_data.order_count/threshold:.1f}x above normal threshold")
                
                # Get user history for context
                user_total_orders = db.query(Order).filter(Order.user_id == user.id).count()
                if user_total_orders > 0:
                    burst_ratio = user_data.order_count / user_total_orders
                    if burst_ratio > 0.5:
                        reasons.append(f"This burst represents {burst_ratio*100:.0f}% of user's total order history")
                
                severity = "critical" if risk_score >= 70 else "high" if risk_score >= 50 else "medium"
                
                anomalies.append({
                    "type": "velocity",
                    "user_id": user.id,
                    "user_email": user.email,
                    "user_name": user.name,
                    "severity": severity,
                    "risk_score": round(risk_score, 1),
                    "reason": reasons[0],  # Primary reason for display
                    "reasons": reasons,  # All detailed reasons
                    "order_count": user_data.order_count,
                    "total_spent": float(user_data.total_spent),
                    "time_window": window_name,
                    "order_rate": round(rate, 2),
                    "first_order": user_data.first_order.isoformat(),
                    "last_order": user_data.last_order.isoformat(),
                    "detection_method": "Velocity Analysis",
                    "explanation": f"User {user.email} placed {user_data.order_count} orders in {window_name} (rate: {rate:.2f}/min). " +
                                   f"This velocity pattern is {'consistent with' if rate > 2 else 'potentially indicative of'} automated ordering.",
                    "recommendation": "Review for bot activity" if rate > 2 else "Monitor user activity"
                })
        
        return sorted(anomalies, key=lambda x: x['risk_score'], reverse=True)
    
    def detect_payment_anomalies(self, db: Session) -> List[Dict[str, Any]]:
        """Detect payment-related anomalies with fraud pattern analysis - checks ALL cancelled orders"""
        anomalies = []
        now = datetime.utcnow()
        
        # Find ALL cancelled orders (not just recent) - for small datasets
        suspicious_cancelled = db.query(Order).filter(
            Order.status == "Cancelled"
        ).all()
        
        for order in suspicious_cancelled:
            reasons = []
            risk_score = 0
            fraud_indicators = []
            
            # Check cancellation timing - any cancelled order is suspicious to some degree
            time_since_creation = (now - order.created_at).total_seconds()
            days_since_creation = time_since_creation / 86400
            
            # Any cancellation gets base score
            risk_score += 10
            reasons.append(f"Order cancelled (₹{order.total_amount:,.0f})")
            
            # Recent cancellations (within last 24h) are more suspicious
            if time_since_creation < 86400:  # 24 hours
                risk_score += 15
                reasons.append("Cancelled within last 24 hours")
                fraud_indicators.append("Recent cancellation")
            elif time_since_creation < 604800:  # 7 days
                risk_score += 5
                reasons.append("Cancelled within last 7 days")
            
            # Check for multiple cancellations from same user - check ALL TIME
            user_cancellations_all = db.query(Order).filter(
                Order.user_id == order.user_id,
                Order.status == "Cancelled"
            ).count()
            
            user_total_orders = db.query(Order).filter(
                Order.user_id == order.user_id
            ).count()
            
            if user_cancellations_all > 3:
                risk_score += 20
                reasons.append(f"User has {user_cancellations_all} total cancellations")
                fraud_indicators.append("Repeat canceller")
                if user_total_orders > 0:
                    cancel_rate = user_cancellations_all / user_total_orders * 100
                    if cancel_rate > 50:
                        risk_score += 15
                        reasons.append(f"CRITICAL: User cancelled {cancel_rate:.0f}% of all orders")
                        fraud_indicators.append("High cancellation rate")
            elif user_cancellations_all > 1:
                risk_score += 10
                reasons.append(f"{user_cancellations_all} cancellations by this user")
            
            # High-value cancellations are more suspicious
            if order.total_amount > 7000:
                risk_score += 15
                reasons.append(f"High-value cancellation: ₹{order.total_amount:,.0f}")
                fraud_indicators.append("High-value cancellation")
            elif order.total_amount > 5000:
                risk_score += 8
                reasons.append(f"Moderate-value cancellation: ₹{order.total_amount:,.0f}")
            
            # Check if multiple users cancelled around same time (coordinated pattern)
            same_day_cancellations = db.query(Order).filter(
                Order.status == "Cancelled",
                func.date(Order.created_at) == func.date(order.created_at)
            ).count()
            
            if same_day_cancellations > 2:
                risk_score += 10
                reasons.append(f"{same_day_cancellations} orders cancelled on same day - possible system issue or coordinated activity")
                fraud_indicators.append("Coordinated pattern")
            
            if reasons:
                user = db.query(User).filter(User.id == order.user_id).first()
                severity = "critical" if risk_score >= 50 else "high" if risk_score >= 30 else "medium" if risk_score >= 15 else "low"
                
                anomalies.append({
                    "order_id": order.order_number,
                    "order_id_db": order.id,
                    "type": "payment",
                    "severity": severity,
                    "risk_score": round(risk_score, 1),
                    "reason": reasons[0],
                    "reasons": reasons,
                    "fraud_indicators": fraud_indicators,
                    "amount": order.total_amount,
                    "user_id": order.user_id,
                    "user_email": user.email if user else "Unknown",
                    "created_at": order.created_at.isoformat(),
                    "cancelled_at": now.isoformat(),
                    "days_since_order": round(days_since_creation, 1),
                    "detection_method": "Payment Pattern Analysis",
                    "explanation": f"Order {order.order_number} (₹{order.total_amount:,.0f}) was cancelled. " +
                                   f"User has {user_cancellations_all}/{user_total_orders} cancelled orders. " +
                                   f"Pattern: {', '.join(fraud_indicators) if fraud_indicators else 'standard cancellation'}.",
                    "recommendation": "Review for fraud" if risk_score >= 40 else "Monitor user"
                })
        
        return sorted(anomalies, key=lambda x: x['risk_score'], reverse=True)
    
    def detect_simple_anomalies(self, db: Session) -> List[Dict[str, Any]]:
        """Simple rule-based anomaly detection for small datasets"""
        anomalies = []
        orders = db.query(Order).all()
        
        if not orders or len(orders) < 2:
            return []
        
        # Calculate basic stats
        amounts = [o.total_amount for o in orders]
        min_amt = min(amounts)
        max_amt = max(amounts)
        avg_amt = sum(amounts) / len(amounts)
        range_amt = max_amt - min_amt
        
        for order in orders:
            reasons = []
            risk_score = 0
            
            # Highest value order
            if order.total_amount == max_amt and len(orders) > 3:
                risk_score += 20
                reasons.append(f"HIGHEST VALUE ORDER: ₹{order.total_amount:,.0f} (max in dataset)")
                reasons.append(f"{((max_amt/avg_amt - 1) * 100):.0f}% above average order value")
            
            # Lowest value order  
            if order.total_amount == min_amt and min_amt < avg_amt * 0.5 and len(orders) > 3:
                risk_score += 15
                reasons.append(f"LOW VALUE ORDER: ₹{order.total_amount:,.0f} (minimum in dataset)")
                reasons.append(f"Significantly below typical range")
            
            # High variation from average
            if avg_amt > 0:
                variation = abs(order.total_amount - avg_amt) / avg_amt
                if variation > 0.8:  # 80% deviation
                    risk_score += 15
                    if order.total_amount > avg_amt:
                        reasons.append(f"High value: ₹{order.total_amount:,.0f} ({variation*100:.0f}% above avg)")
                    else:
                        reasons.append(f"Low value: ₹{order.total_amount:,.0f} ({variation*100:.0f}% below avg)")
            
            # Pending orders older than 7 days
            if order.status == "Pending":
                days_old = (datetime.utcnow() - order.created_at).days
                if days_old > 7:
                    risk_score += 20
                    reasons.append(f"STALE PENDING: Order pending for {days_old} days")
                    reasons.append("Long-pending orders may indicate payment issues")
            
            # Cancelled orders
            if order.status == "Cancelled":
                risk_score += 25
                reasons.append(f"CANCELLED ORDER: ₹{order.total_amount:,.0f}")
                
                # Check user's cancellation pattern
                user_cancels = sum(1 for o in orders if o.user_id == order.user_id and o.status == "Cancelled")
                user_total = sum(1 for o in orders if o.user_id == order.user_id)
                if user_total > 0 and user_cancels / user_total > 0.3:
                    reasons.append(f"User cancellation rate: {(user_cancels/user_total*100):.0f}% ({user_cancels}/{user_total})")
            
            if reasons:
                severity = "high" if risk_score >= 30 else "medium" if risk_score >= 15 else "low"
                
                anomalies.append({
                    "order_id": order.order_number,
                    "order_id_db": order.id,
                    "type": "simple_rule",
                    "severity": severity,
                    "risk_score": round(risk_score, 1),
                    "reason": reasons[0],
                    "reasons": reasons,
                    "amount": order.total_amount,
                    "user_id": order.user_id,
                    "status": order.status,
                    "created_at": order.created_at.isoformat(),
                    "detection_method": "Rule-Based Analysis",
                    "explanation": f"Order {order.order_number} flagged by rule-based detection. Value range in dataset: ₹{min_amt:,.0f} - ₹{max_amt:,.0f}"
                })
        
        return sorted(anomalies, key=lambda x: x['risk_score'], reverse=True)
    
    def get_anomaly_heatmap_data(self, db: Session) -> Dict[str, Any]:
        """Get real-time anomaly heatmap data - returns 2D array for frontend compatibility"""
        # Frontend expects: days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
        # But Python datetime weekday(): Monday=0, Sunday=6
        # So we need to reorder: Sun(6), Mon(0), Tue(1), Wed(2), Thu(3), Fri(4), Sat(5)
        frontend_days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
        python_to_frontend = [6, 0, 1, 2, 3, 4, 5]  # Map Python weekday to frontend index
        
        cutoff_date = datetime.utcnow() - timedelta(days=7)
        orders = db.query(Order).filter(Order.created_at >= cutoff_date).all()
        
        # Calculate statistics for anomaly detection
        amounts = [o.total_amount for o in orders] if orders else []
        if amounts:
            avg = sum(amounts) / len(amounts)
            std = (sum((x - avg) ** 2 for x in amounts) / len(amounts)) ** 0.5 if len(amounts) > 1 else 1
        else:
            avg, std = 0, 1
        
        # Build 2D array [day][hour] for frontend
        # Initialize with zeros
        heatmap_2d = [[0 for _ in range(24)] for _ in range(7)]
        anomaly_2d = [[0 for _ in range(24)] for _ in range(7)]
        
        for day in range(7):  # Python weekday: 0=Mon, 6=Sun
            frontend_day_index = python_to_frontend[day]
            for hour in range(24):
                # Count orders and anomalies for this day/hour
                day_orders = [o for o in orders if o.created_at.weekday() == day 
                             and o.created_at.hour == hour]
                
                order_count = len(day_orders)
                
                # Calculate anomaly count
                anomaly_count = 0
                for order in day_orders:
                    if std > 0 and abs(order.total_amount - avg) / std > 2:
                        anomaly_count += 1
                
                heatmap_2d[frontend_day_index][hour] = order_count
                anomaly_2d[frontend_day_index][hour] = anomaly_count
        
        # Also return detailed data for advanced visualizations
        detailed_data = []
        for day_idx, day_name in enumerate(frontend_days):
            for hour in range(24):
                detailed_data.append({
                    "day": day_name,
                    "day_index": day_idx,
                    "hour": hour,
                    "order_count": heatmap_2d[day_idx][hour],
                    "anomaly_count": anomaly_2d[day_idx][hour],
                    "anomaly_rate": round(anomaly_2d[day_idx][hour] / heatmap_2d[day_idx][hour] * 100, 1) if heatmap_2d[day_idx][hour] > 0 else 0
                })
        
        max_value = max([max(row) for row in heatmap_2d]) if heatmap_2d else 0
        
        return {
            "data": heatmap_2d,  # 2D array for frontend compatibility
            "anomaly_data": anomaly_2d,  # Anomaly heatmap
            "detailed_data": detailed_data,
            "days": frontend_days,
            "hours": list(range(24)),
            "max_value": max_value
        }
    
    def get_fraud_metrics(self, db: Session) -> Dict[str, Any]:
        """Get real-time fraud detection metrics - flat structure for frontend compatibility"""
        # Time ranges
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = now - timedelta(days=7)
        
        # Total orders in different timeframes
        total_orders_today = db.query(Order).filter(Order.created_at >= today_start).count()
        total_orders_week = db.query(Order).filter(Order.created_at >= week_start).count()
        total_orders_all = db.query(Order).count()
        
        # Count orders manually marked as Fraud
        marked_fraud_all = db.query(Order).filter(Order.status == "Fraud").count()
        marked_fraud_today = db.query(Order).filter(Order.status == "Fraud", Order.created_at >= today_start).count()
        marked_fraud_week = db.query(Order).filter(Order.status == "Fraud", Order.created_at >= week_start).count()
        
        # Get all anomalies from detection
        all_anomalies = self.detect_anomalies_ml(db) + self.detect_anomalies_statistical(db)
        
        # Critical and high risk anomalies
        critical_anomalies = [a for a in all_anomalies if a.get("risk_score", 0) >= 70]
        high_anomalies = [a for a in all_anomalies if 50 <= a.get("risk_score", 0) < 70]
        medium_anomalies = [a for a in all_anomalies if 30 <= a.get("risk_score", 0) < 50]
        
        # Velocity anomalies
        velocity_anomalies = self.detect_velocity_anomalies(db)
        
        # Payment anomalies
        payment_anomalies = self.detect_payment_anomalies(db)
        
        # Combined metrics
        total_anomalies = len(all_anomalies) + len(velocity_anomalies) + len(payment_anomalies)
        
        # Calculate fraud rates - include both detected critical anomalies AND manually marked fraud
        fraud_rate = round(((len(critical_anomalies) + marked_fraud_all) / total_orders_all * 100), 1) if total_orders_all > 0 else 0
        fraud_rate_today = round(((len([a for a in critical_anomalies if a.get('created_at', '').startswith(str(today_start.date()))]) + marked_fraud_today) / total_orders_today * 100), 2) if total_orders_today > 0 else 0
        
        # Calculate cancellation rate
        cancelled_orders = db.query(Order).filter(Order.status == "Cancelled").count()
        cancellation_rate = round((cancelled_orders / total_orders_all * 100), 1) if total_orders_all > 0 else 0
        
        # Count fraud indicators from payment anomalies
        payment_fraud_indicators = sum(len(a.get('fraud_indicators', [])) for a in payment_anomalies)
        
        # Return flat structure that matches frontend expectations
        return {
            "detected_anomalies": total_anomalies,
            "fraud_rate": fraud_rate,
            "cancellation_rate": cancellation_rate,
            "total_orders": total_orders_all,
            # Additional detailed metrics for advanced UI
            "timestamp": now.isoformat(),
            "time_ranges": {
                "today": total_orders_today,
                "week": total_orders_week,
                "all_time": total_orders_all
            },
            "fraud_rates": {
                "today": fraud_rate_today,
                "week": round(((len(critical_anomalies) + marked_fraud_week) / total_orders_week * 100), 2) if total_orders_week > 0 else 0,
                "current_percentage": fraud_rate,
                "marked_fraud_count": marked_fraud_all,
                "trend": "increasing" if (total_orders_today > 0 and len(critical_anomalies) > 0) or marked_fraud_today > 0 else "stable"
            },
            "anomaly_counts": {
                "critical": len(critical_anomalies),
                "high": len(high_anomalies),
                "medium": len(medium_anomalies),
                "velocity": len(velocity_anomalies),
                "payment": len(payment_anomalies),
                "total": total_anomalies
            },
            "risk_distribution": {
                "critical": len(critical_anomalies),
                "high": len(high_anomalies),
                "medium": len(medium_anomalies),
                "low": len(all_anomalies) - len(critical_anomalies) - len(high_anomalies) - len(medium_anomalies)
            },
            "detection_methods": {
                "ml_based": len(self.detect_anomalies_ml(db)),
                "statistical": len(self.detect_anomalies_statistical(db)),
                "velocity": len(velocity_anomalies),
                "payment": len(payment_anomalies)
            },
            "recent_critical": critical_anomalies[:5],
            "average_risk_score": round(
                sum(a.get("risk_score", 0) for a in all_anomalies) / len(all_anomalies), 1
            ) if all_anomalies else 0
        }
    
    def get_live_anomaly_feed(self, db: Session, limit: int = 50) -> List[Dict[str, Any]]:
        """Get real-time live feed of all anomalies sorted by risk"""
        all_anomalies = []
        
        # Collect all anomalies
        all_anomalies.extend(self.detect_anomalies_ml(db))
        all_anomalies.extend(self.detect_anomalies_statistical(db))
        all_anomalies.extend(self.detect_velocity_anomalies(db))
        all_anomalies.extend(self.detect_payment_anomalies(db))
        
        # Sort by risk score (highest first), then by timestamp
        all_anomalies.sort(key=lambda x: (x.get('risk_score', 0), x.get('created_at', '')), reverse=True)
        
        # Add detection timestamp
        for anomaly in all_anomalies:
            anomaly['detected_at'] = datetime.utcnow().isoformat()
        
        return all_anomalies[:limit]
    
    def mark_as_fraud(self, order_id: int, db: Session) -> bool:
        """Mark an order as fraudulent and add to fraud log"""
        try:
            order = db.query(Order).filter(Order.id == order_id).first()
            if order:
                old_status = order.status
                order.status = "Fraud"
                db.commit()
                print(f"[FRAUD] Order {order.order_number} (ID: {order_id}) marked as fraud. Old status: {old_status}")
                return True
            else:
                print(f"[FRAUD] Order ID {order_id} not found")
                return False
        except Exception as e:
            db.rollback()
            print(f"[FRAUD] Error marking order {order_id} as fraud: {e}")
            return False
    
    def detect_order_anomalies(self, db: Session) -> Dict[str, Any]:
        """Detect order anomalies - backward compatible wrapper"""
        all_anomalies = []
        all_anomalies.extend(self.detect_anomalies_ml(db))
        all_anomalies.extend(self.detect_anomalies_statistical(db))
        all_anomalies.extend(self.detect_velocity_anomalies(db))
        all_anomalies.extend(self.detect_payment_anomalies(db))
        
        return {
            "anomalies": all_anomalies,
            "count": len(all_anomalies),
            "generated_at": datetime.utcnow().isoformat()
        }
    
    def detect_inventory_anomalies(self, db: Session) -> Dict[str, Any]:
        """Detect inventory anomalies - placeholder for backward compatibility"""
        # For now, return empty as inventory anomalies need separate logic
        return {
            "anomalies": [],
            "count": 0,
            "generated_at": datetime.utcnow().isoformat()
        }

    def detect_marked_fraud_orders(self, db: Session) -> List[Dict[str, Any]]:
        """Detect orders that have been manually marked as fraud"""
        fraud_orders = db.query(Order).filter(Order.status == "Fraud").all()
        anomalies = []
        
        for order in fraud_orders:
            user = db.query(User).filter(User.id == order.user_id).first()
            anomalies.append({
                "order_id": order.order_number,
                "order_id_db": order.id,
                "type": "manual_fraud",
                "severity": "critical",
                "risk_score": 100.0,
                "reason": "ORDER MARKED AS FRAUD by admin",
                "reasons": ["Manually flagged as fraudulent", "Requires immediate investigation"],
                "amount": order.total_amount,
                "user_id": order.user_id,
                "user_email": user.email if user else "Unknown",
                "user_name": user.name if user else "Unknown",
                "created_at": order.created_at.isoformat(),
                "status": order.status,
                "detection_method": "Manual Review",
                "explanation": f"Order {order.order_number} was manually marked as fraudulent by an administrator."
            })
        
        return anomalies
    
    def get_comprehensive_anomaly_report(self, db: Session) -> Dict[str, Any]:
        """Get comprehensive real-time anomaly detection report"""
        now = datetime.utcnow()
        
        # Get all detection results
        ml_anomalies = self.detect_anomalies_ml(db)
        statistical_anomalies = self.detect_anomalies_statistical(db)
        velocity_anomalies = self.detect_velocity_anomalies(db)
        payment_anomalies = self.detect_payment_anomalies(db)
        simple_anomalies = self.detect_simple_anomalies(db)  # Always run for small datasets
        marked_fraud_anomalies = self.detect_marked_fraud_orders(db)  # Include manually marked fraud
        
        all_anomalies = ml_anomalies + statistical_anomalies + velocity_anomalies + payment_anomalies + simple_anomalies + marked_fraud_anomalies
        
        # Get fraud metrics
        fraud_metrics = self.get_fraud_metrics(db)
        
        # Get heatmap data
        heatmap = self.get_anomaly_heatmap_data(db)
        
        # Calculate summary statistics
        critical_count = len([a for a in all_anomalies if a.get('risk_score', 0) >= 70])
        high_count = len([a for a in all_anomalies if 50 <= a.get('risk_score', 0) < 70])
        
        # Get user anomalies (for frontend compatibility)
        user_anomalies = self._get_user_anomalies_for_frontend(db, all_anomalies)
        
        return {
            "report_generated_at": now.isoformat(),
            "summary": {
                "total_anomalies": len(all_anomalies),
                "critical": critical_count,
                "high": high_count,
                "requires_immediate_attention": critical_count > 0
            },
            "fraud_metrics": fraud_metrics,
            "anomalies": all_anomalies[:50],  # Top 50 by risk
            "heatmap_data": heatmap,
            "detection_summary": {
                "ml_based": len(ml_anomalies),
                "statistical": len(statistical_anomalies),
                "velocity": len(velocity_anomalies),
                "payment": len(payment_anomalies),
                "simple_rule": len(simple_anomalies),
                "manual_fraud": len(marked_fraud_anomalies)
            },
            "top_risk_users": self._get_top_risk_users(db, all_anomalies),
            "user_anomalies": user_anomalies,  # Frontend compatibility
            "trends": {
                "fraud_rate": fraud_metrics["fraud_rates"]["today"],
                "anomaly_count": len(all_anomalies),
                "risk_level": "HIGH" if critical_count > 5 else "MEDIUM" if critical_count > 0 else "LOW"
            }
        }
    
    def _get_user_anomalies_for_frontend(self, db: Session, anomalies: List[Dict], limit: int = 10) -> List[Dict]:
        """Get user anomalies formatted for frontend display"""
        user_data = {}
        now = datetime.utcnow()
        
        for anomaly in anomalies:
            user_id = anomaly.get('user_id')
            if not user_id:
                continue
            
            if user_id not in user_data:
                user = db.query(User).filter(User.id == user_id).first()
                user_data[user_id] = {
                    'user_id': user_id,
                    'user_email': anomaly.get('user_email', user.email if user else 'Unknown'),
                    'total_risk_score': 0,
                    'anomaly_count': 0,
                    'reasons': [],
                    'total_spent': 0,
                    'order_count': 0
                }
            
            user_data[user_id]['total_risk_score'] += anomaly.get('risk_score', 0)
            user_data[user_id]['anomaly_count'] += 1
            if anomaly.get('reason'):
                user_data[user_id]['reasons'].append(anomaly.get('reason'))
            if anomaly.get('amount'):
                user_data[user_id]['total_spent'] += anomaly.get('amount', 0)
            if anomaly.get('order_count'):
                user_data[user_id]['order_count'] = max(user_data[user_id]['order_count'], anomaly.get('order_count', 0))
        
        # Get order count from database for each user
        for user_id in user_data:
            recent_order_count = db.query(Order).filter(
                Order.user_id == user_id,
                Order.created_at >= now - timedelta(days=7)
            ).count()
            user_data[user_id]['order_count'] = max(user_data[user_id]['order_count'], recent_order_count)
        
        # Format for frontend
        result = []
        for user_id, data in user_data.items():
            result.append({
                'user_id': data['user_id'],
                'user_email': data['user_email'],
                'reason': '; '.join(data['reasons'][:2]) if data['reasons'] else 'Multiple suspicious activities detected',
                'order_count': data['order_count'],
                'total_spent': data['total_spent'],
                'risk_score': data['total_risk_score'],
                'anomaly_count': data['anomaly_count']
            })
        
        # Sort by risk score and return top users
        result.sort(key=lambda x: x['risk_score'], reverse=True)
        return result[:limit]
    
    def _get_top_risk_users(self, db: Session, anomalies: List[Dict], limit: int = 10) -> List[Dict]:
        """Get users with highest risk scores"""
        user_risk = {}
        
        for anomaly in anomalies:
            user_id = anomaly.get('user_id')
            if not user_id:
                continue
            
            if user_id not in user_risk:
                user_risk[user_id] = {
                    'user_id': user_id,
                    'email': anomaly.get('user_email', 'Unknown'),
                    'total_risk_score': 0,
                    'anomaly_count': 0,
                    'reasons': []
                }
            
            user_risk[user_id]['total_risk_score'] += anomaly.get('risk_score', 0)
            user_risk[user_id]['anomaly_count'] += 1
            if anomaly.get('reason'):
                user_risk[user_id]['reasons'].append(anomaly.get('reason'))
        
        # Sort by total risk score
        sorted_users = sorted(user_risk.values(), key=lambda x: x['total_risk_score'], reverse=True)
        
        return sorted_users[:limit]


anomaly_detection_service = AnomalyDetectionService()
