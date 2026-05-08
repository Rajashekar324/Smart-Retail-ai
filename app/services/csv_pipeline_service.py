from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[2]
CSV_CANDIDATES = [
    ROOT_DIR / "backend" / "data" / "final_analytics.csv",
    ROOT_DIR / "data" / "final_analytics.csv",
    ROOT_DIR / "sample_sales_data.csv",
]


def find_analytics_csv() -> Path:
    for path in CSV_CANDIDATES:
        if path.exists():
            return path

    raise FileNotFoundError(
        "Analytics CSV file not found. Expected backend/data/final_analytics.csv or data/final_analytics.csv."
    )


def load_csv_data() -> pd.DataFrame:
    csv_path = find_analytics_csv()
    df = pd.read_csv(csv_path)

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

    if "revenue" in df.columns:
        df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce").fillna(0.0)

    if "orders" in df.columns:
        df["orders"] = pd.to_numeric(df["orders"], errors="coerce").fillna(0).astype(int)

    return df


def build_trend(df: pd.DataFrame) -> List[Dict[str, Any]]:
    if "date" not in df.columns:
        return []

    trend = []
    sorted_df = df.sort_values("date")

    for row in sorted_df.to_dict(orient="records"):
        trend.append({
            "date": row.get("date").strftime("%Y-%m-%d") if row.get("date") is not None else None,
            "revenue": float(row.get("revenue", 0) or 0),
            "orders": int(row.get("orders", 0) or 0),
        })

    return trend


def build_quality_report(df: pd.DataFrame) -> Dict[str, Any]:
    checks = []
    if "revenue" in df.columns:
        checks.append((df["revenue"] >= 0).all())
    if "orders" in df.columns:
        checks.append((df["orders"] >= 0).all())
    if "date" in df.columns:
        checks.append(df["date"].notna().all())

    total_checks = max(len(checks), 1)
    passed_checks = sum(bool(item) for item in checks)
    failed_checks = total_checks - passed_checks
    quality_score = round((passed_checks / total_checks) * 100, 2)
    status = "PASS" if quality_score >= 95 else "WARNING" if quality_score >= 80 else "FAIL"

    return {
        "overall_score": quality_score,
        "total_checks": total_checks,
        "passed_checks": passed_checks,
        "failed_checks": failed_checks,
        "status": status,
    }


def build_bronze_tables(df: pd.DataFrame) -> Dict[str, List[Dict[str, Any]]]:
    orders = []
    for index, row in df.iterrows():
        orders.append({
            "record_id": index + 1,
            "date": row.get("date").strftime("%Y-%m-%d") if row.get("date") is not None else None,
            "revenue": float(row.get("revenue", 0) or 0),
            "orders": int(row.get("orders", 0) or 0),
        })

    products = []
    if "revenue" in df.columns:
        top_rows = df.sort_values("revenue", ascending=False).head(6).reset_index(drop=True)
        for idx, row in top_rows.iterrows():
            products.append({
                "product_id": idx + 1,
                "product_name": f"Product {idx + 1}",
                "category": "Smart Retail",
                "price": round((row.get("revenue", 0) or 0) / max(int(row.get("orders", 1) or 1), 1), 2),
                "stock": max(int((row.get("orders", 0) or 0) * 3), 1),
                "daily_revenue": float(row.get("revenue", 0) or 0),
            })

    users = []
    if "date" in df.columns:
        sample_rows = df.sort_values("date").head(6).reset_index(drop=True)
        for idx, row in sample_rows.iterrows():
            users.append({
                "user_id": idx + 1,
                "name": f"Customer {idx + 1}",
                "email": f"customer{idx + 1}@example.com",
                "total_orders": int(row.get("orders", 0) or 0),
                "lifetime_value": round(float(row.get("revenue", 0) or 0), 2),
                "joined_date": row.get("date").strftime("%Y-%m-%d") if row.get("date") is not None else None,
            })

    support_tickets = []
    anomalies = get_anomaly_records(df)
    for idx, anomaly in enumerate(anomalies[:6]):
        support_tickets.append({
            "ticket_id": f"TKT-{1000 + idx}",
            "customer_email": f"alert{idx + 1}@example.com",
            "subject": "Revenue spike detected",
            "status": "Open" if idx % 2 == 0 else "Investigating",
            "priority": "High" if anomaly["severity"] == "High" else "Medium",
            "created_at": anomaly["date"],
            "sentiment": "neutral",
        })

    return {
        "orders": orders,
        "products": products,
        "users": users,
        "support_tickets": support_tickets,
    }


def get_anomaly_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    anomalies = []
    if "revenue" not in df.columns or df["revenue"].empty:
        return anomalies

    mean = df["revenue"].mean()
    std = df["revenue"].std(ddof=0)
    if std <= 0:
        return anomalies

    for _, row in df.iterrows():
        revenue = float(row.get("revenue", 0) or 0)
        z = abs((revenue - mean) / std)
        if z >= 2.5:
            anomalies.append({
                "date": row.get("date").strftime("%Y-%m-%d") if row.get("date") is not None else None,
                "revenue": revenue,
                "orders": int(row.get("orders", 0) or 0),
                "z_score": round(z, 2),
                "severity": "High" if z > 3 else "Medium",
                "is_anomaly": True,
            })

    return anomalies


def build_silver_tables(df: pd.DataFrame) -> Dict[str, List[Dict[str, Any]]]:
    dim_customers = []
    product_rows = df.sort_values("revenue", ascending=False).head(6).reset_index(drop=True)
    for idx, row in product_rows.iterrows():
        dim_customers.append({
            "customer_id": idx + 1,
            "name": f"Customer {idx + 1}",
            "total_orders": int(row.get("orders", 0) or 0),
            "total_spent": round(float(row.get("revenue", 0) or 0), 2),
            "customer_segment": "Champions" if idx == 0 else "Loyal" if idx < 3 else "Standard",
            "effective_date": row.get("date").strftime("%Y-%m-%d") if row.get("date") is not None else None,
            "is_current": True,
        })

    dim_products = []
    for idx, row in product_rows.iterrows():
        revenue = float(row.get("revenue", 0) or 0)
        dim_products.append({
            "product_id": idx + 1,
            "product_name": f"Product {idx + 1}",
            "category": "Retail",
            "total_sold": int(row.get("orders", 0) or 0),
            "total_revenue": round(revenue, 2),
            "stock": max(int((row.get("orders", 0) or 0) * 2), 5),
            "stock_status": "Low Stock" if revenue < 5000 else "In Stock",
            "effective_date": row.get("date").strftime("%Y-%m-%d") if row.get("date") is not None else None,
            "is_current": True,
        })

    fact_orders = []
    for _, row in df.iterrows():
        fact_orders.append({
            "order_date": row.get("date").strftime("%Y-%m-%d") if row.get("date") is not None else None,
            "order_count": int(row.get("orders", 0) or 0),
            "total_revenue": float(row.get("revenue", 0) or 0),
            "average_value": round(float(row.get("revenue", 0) or 0) / max(int(row.get("orders", 0) or 1), 1), 2),
            "order_year": row.get("date").year if row.get("date") is not None else None,
            "is_weekend": row.get("date").weekday() >= 5 if row.get("date") is not None else False,
        })

    fact_support_tickets = []
    anomalies = get_anomaly_records(df)
    for idx, anomaly in enumerate(anomalies[:6]):
        fact_support_tickets.append({
            "ticket_id": idx + 1,
            "ticket_subject": "Data quality alert",
            "created_at": anomaly["date"],
            "status": "Open" if idx % 2 == 0 else "Closed",
            "priority": "High" if anomaly["severity"] == "High" else "Medium",
            "resolution_time_hours": 24 - idx * 2,
        })

    return {
        "dim_customers": dim_customers,
        "dim_products": dim_products,
        "fact_orders": fact_orders,
        "fact_support_tickets": fact_support_tickets,
    }


def build_gold_tables(df: pd.DataFrame) -> Dict[str, List[Dict[str, Any]]]:
    sales_daily = []
    for _, row in df.sort_values("date").iterrows():
        sales_daily.append({
            "date": row.get("date").strftime("%Y-%m-%d") if row.get("date") is not None else None,
            "total_orders": int(row.get("orders", 0) or 0),
            "total_revenue": float(row.get("revenue", 0) or 0),
            "avg_order_value": round(float(row.get("revenue", 0) or 0) / max(int(row.get("orders", 0) or 1), 1), 2),
            "unique_customers": max(int(row.get("orders", 0) or 0) // 2, 1),
            "profit_estimate": round(float(row.get("revenue", 0) or 0) * 0.35, 2),
        })

    customer_360 = []
    for idx, row in enumerate(df.sort_values("revenue", ascending=False).head(6).to_dict(orient="records")):
        customer_360.append({
            "customer_id": idx + 1,
            "customer_name": f"Customer {idx + 1}",
            "total_spent": round(float(row.get("revenue", 0) or 0), 2),
            "rfm_segment": "Champions" if idx < 2 else "Loyal" if idx < 4 else "Standard",
            "churn_risk_segment": "Low Risk" if idx < 3 else "Medium Risk",
            "recency": idx * 3 + 5,
            "frequency": int(row.get("orders", 0) or 0),
        })

    inventory_analytics = []
    for idx, row in enumerate(df.sort_values("revenue", ascending=False).head(6).to_dict(orient="records")):
        inventory_analytics.append({
            "product_id": idx + 1,
            "product_name": f"Product {idx + 1}",
            "stock": max(int((row.get("orders", 0) or 0) * 5), 10),
            "daily_velocity": round((row.get("orders", 0) or 0) / 30, 2),
            "days_of_inventory": round(max(int((row.get("orders", 0) or 0) * 5), 10) / max((row.get("orders", 0) or 1) / 30, 1), 1),
            "reorder_recommended": (row.get("orders", 0) or 0) > 10,
            "abc_classification": "A" if idx < 2 else "B" if idx < 4 else "C",
        })

    anomaly_features = get_anomaly_records(df)

    return {
        "sales_daily": sales_daily,
        "customer_360": customer_360,
        "inventory_analytics": inventory_analytics,
        "anomaly_features": anomaly_features,
    }


def get_layer_payload(layer_name: str, table_name: Optional[str] = None) -> Dict[str, Any]:
    df = load_csv_data()
    layer_name = layer_name.lower()
    if layer_name == "bronze":
        tables = build_bronze_tables(df)
    elif layer_name == "silver":
        tables = build_silver_tables(df)
    elif layer_name == "gold":
        tables = build_gold_tables(df)
    else:
        raise ValueError(f"Unknown layer: {layer_name}")

    if table_name:
        if table_name not in tables:
            raise ValueError(f"Unknown table: {table_name}")
        return {"layer": layer_name, "table": table_name, "records": tables[table_name]}

    return {"layer": layer_name, "tables": tables}


def get_analytics_payload() -> Dict[str, Any]:
    df = load_csv_data()
    trend = build_trend(df)
    quality = build_quality_report(df)
    anomalies = get_anomaly_records(df)

    total_revenue = float(df["revenue"].sum()) if "revenue" in df.columns else 0.0
    total_orders = int(df["orders"].sum()) if "orders" in df.columns else 0
    avg_order_value = round(total_revenue / total_orders, 2) if total_orders > 0 else 0.0
    period_start = df["date"].min().strftime("%Y-%m-%d") if "date" in df.columns and not df["date"].isna().all() else None
    period_end = df["date"].max().strftime("%Y-%m-%d") if "date" in df.columns and not df["date"].isna().all() else None

    return {
        "summary": {
            "total_revenue": total_revenue,
            "total_orders": total_orders,
            "avg_order_value": avg_order_value,
            "records": len(df),
            "period_start": period_start,
            "period_end": period_end,
        },
        "layer_counts": {
            "raw": len(df),
            "staging": max(len(df) // 7, 1),
            "curated": len(trend),
        },
        "quality": quality,
        "trend": trend,
        "anomalies": anomalies,
        "timestamp": datetime.utcnow().isoformat(),
    }
