# Databricks notebook source
# MAGIC %md
# MAGIC # Smart Retail: Data Quality Monitoring
# MAGIC 
# MAGIC Continuous data quality monitoring with:
# MAGIC - Schema validation
# MAGIC - Data completeness checks
# MAGIC - Statistical profiling
# MAGIC - Anomaly detection on data quality
# MAGIC 
# MAGIC Results are logged to Delta table for trend analysis.

# COMMAND ----------

# DBTITLE 1,Initialize
from pyspark.sql import SparkSession
from pyspark.sql.functions import *
from pyspark.sql.window import Window
from delta.tables import DeltaTable
import json
from datetime import date, datetime

dbutils.widgets.text("staging_path", "abfss://staging@smartretailstore.dfs.core.windows.net", "Staging Path")
dbutils.widgets.text("curated_path", "abfss://curated@smartretailstore.dfs.core.windows.net", "Curated Path")
dbutils.widgets.text("execution_date", date.today().isoformat(), "Execution Date")

staging_path = dbutils.widgets.get("staging_path")
curated_path = dbutils.widgets.get("curated_path")
execution_date = dbutils.widgets.get("execution_date")

print(f"Monitoring data quality for execution: {execution_date}")

# COMMAND ----------

# DBTITLE 1,Create Quality Log Table (if not exists)
spark.sql("""
    CREATE TABLE IF NOT EXISTS monitoring.data_quality_log (
        check_timestamp TIMESTAMP,
        execution_date STRING,
        table_name STRING,
        check_name STRING,
        check_type STRING,
        passed BOOLEAN,
        expected_value STRING,
        actual_value STRING,
        severity STRING,
        details STRING
    ) USING DELTA
    LOCATION 'abfss://monitoring@smartretailstore.dfs.core.windows.net/data_quality_log'
""")

# COMMAND ----------

# DBTITLE 1,Quality Check Functions
def log_quality_check(table_name, check_name, check_type, passed, expected, actual, severity="medium", details=""):
    """Log quality check to monitoring table"""
    log_entry = spark.createDataFrame([{
        "check_timestamp": datetime.now(),
        "execution_date": execution_date,
        "table_name": table_name,
        "check_name": check_name,
        "check_type": check_type,
        "passed": passed,
        "expected_value": str(expected),
        "actual_value": str(actual),
        "severity": severity,
        "details": details
    }])
    
    log_entry.write.format("delta").mode("append").saveAsTable("monitoring.data_quality_log")
    return passed

def check_completeness(df, table_name, column, threshold=0.95):
    """Check data completeness (non-null percentage)"""
    total = df.count()
    non_null = df.filter(col(column).isNotNull()).count()
    completeness = non_null / total if total > 0 else 0
    passed = completeness >= threshold
    
    log_quality_check(
        table_name=table_name,
        check_name=f"{column}_completeness",
        check_type="completeness",
        passed=passed,
        expected=f">={threshold*100}%",
        actual=f"{completeness*100:.2f}%",
        severity="high" if not passed else "low",
        details=f"{non_null}/{total} non-null values"
    )
    return passed

def check_uniqueness(df, table_name, column):
    """Check column uniqueness"""
    total = df.count()
    distinct = df.select(column).distinct().count()
    passed = total == distinct
    
    log_quality_check(
        table_name=table_name,
        check_name=f"{column}_uniqueness",
        check_type="uniqueness",
        passed=passed,
        expected=f"{total} distinct",
        actual=f"{distinct} distinct",
        severity="critical" if not passed else "low",
        details=f"{total - distinct} duplicates found" if not passed else "All unique"
    )
    return passed

def check_range(df, table_name, column, min_val, max_val):
    """Check value range"""
    out_of_range = df.filter((col(column) < min_val) | (col(column) > max_val)).count()
    passed = out_of_range == 0
    
    log_quality_check(
        table_name=table_name,
        check_name=f"{column}_range",
        check_type="range",
        passed=passed,
        expected=f"[{min_val}, {max_val}]",
        actual=f"{out_of_range} out of range",
        severity="high" if not passed else "low"
    )
    return passed

def check_referential_integrity(parent_df, child_df, parent_col, child_col, parent_table, child_table):
    """Check referential integrity"""
    parent_ids = parent_df.select(parent_col).distinct()
    child_ids = child_df.select(child_col).distinct()
    
    orphaned = child_ids.join(parent_ids, child_col == parent_col, "left_anti").count()
    passed = orphaned == 0
    
    log_quality_check(
        table_name=child_table,
        check_name=f"fk_{child_col}_integrity",
        check_type="referential_integrity",
        passed=passed,
        expected="0 orphans",
        actual=f"{orphaned} orphans",
        severity="critical" if not passed else "low",
        details=f"Foreign key {child_col} references {parent_table}.{parent_col}"
    )
    return passed

def check_freshness(table_name, timestamp_col, max_delay_hours=24):
    """Check data freshness"""
    df = spark.read.format("delta").load(f"{staging_path}/{table_name}")
    max_ts = df.select(max(timestamp_col)).collect()[0][0]
    
    if max_ts:
        delay_hours = (datetime.now() - max_ts).total_seconds() / 3600
        passed = delay_hours <= max_delay_hours
    else:
        delay_hours = float('inf')
        passed = False
    
    log_quality_check(
        table_name=table_name,
        check_name=f"{timestamp_col}_freshness",
        check_type="freshness",
        passed=passed,
        expected=f"<={max_delay_hours}h",
        actual=f"{delay_hours:.1f}h delay",
        severity="medium" if not passed else "low"
    )
    return passed

# COMMAND ----------

# DBTITLE 1,Run Quality Checks on Staging Tables
print("Running quality checks on staging tables...")
quality_results = []

# Check Dim Customers
customers = spark.read.format("delta").load(f"{staging_path}/dim_customers")
quality_results.append(check_completeness(customers, "dim_customers", "email", 1.0))
quality_results.append(check_completeness(customers, "dim_customers", "name", 1.0))
quality_results.append(check_uniqueness(customers, "dim_customers", "email"))
quality_results.append(check_range(customers, "dim_customers", "total_spent", 0, 1000000))

# Check Dim Products
products = spark.read.format("delta").load(f"{staging_path}/dim_products")
quality_results.append(check_completeness(products, "dim_products", "sku", 1.0))
quality_results.append(check_completeness(products, "dim_products", "name", 1.0))
quality_results.append(check_uniqueness(products, "dim_products", "sku"))
quality_results.append(check_range(products, "dim_products", "price", 0.01, 100000))
quality_results.append(check_range(products, "dim_products", "stock", 0, 100000))

# Check Fact Orders
orders = spark.read.format("delta").load(f"{staging_path}/fact_orders")
quality_results.append(check_completeness(orders, "fact_orders", "order_number", 1.0))
quality_results.append(check_completeness(orders, "fact_orders", "total_amount", 1.0))
quality_results.append(check_uniqueness(orders, "fact_orders", "order_number"))
quality_results.append(check_range(orders, "fact_orders", "total_amount", 0, 1000000))

# Check Fact Order Items
items = spark.read.format("delta").load(f"{staging_path}/fact_order_items")
quality_results.append(check_range(items, "fact_order_items", "quantity", 1, 1000))
quality_results.append(check_range(items, "fact_order_items", "unit_price", 0.01, 100000))

# Referential Integrity
quality_results.append(check_referential_integrity(
    customers, orders, "id", "user_id", "dim_customers", "fact_orders"
))
quality_results.append(check_referential_integrity(
    orders, items, "id", "order_id", "fact_orders", "fact_order_items"
))
quality_results.append(check_referential_integrity(
    products, items, "id", "product_id", "dim_products", "fact_order_items"
))

# COMMAND ----------

# DBTITLE 1,Run Quality Checks on Curated Tables
print("\nRunning quality checks on curated tables...")

# Check Sales Daily
sales_daily = spark.read.format("delta").load(f"{curated_path}/sales_daily")
quality_results.append(check_completeness(sales_daily, "sales_daily", "created_at", 1.0))
quality_results.append(check_range(sales_daily, "sales_daily", "total_revenue", 0, 10000000))
quality_results.append(check_range(sales_daily, "sales_daily", "cancellation_rate", 0, 100))

# Check Customer 360
customer_360 = spark.read.format("delta").load(f"{curated_path}/customer_360")
quality_results.append(check_completeness(customer_360, "customer_360", "rfm_segment", 0.95))
quality_results.append(check_range(customer_360, "customer_360", "churn_risk_score", 0, 1))

# Check Inventory Analytics
inventory = spark.read.format("delta").load(f"{curated_path}/inventory_analytics")
quality_results.append(check_range(inventory, "inventory_analytics", "days_of_inventory", 0, 1000))

# COMMAND ----------

# DBTITLE 1,Generate Quality Summary Report
def generate_quality_report():
    """Generate quality summary for current execution"""
    
    # Get all checks for today
    checks_df = spark.table("monitoring.data_quality_log").filter(
        col("execution_date") == execution_date
    )
    
    total_checks = checks_df.count()
    passed_checks = checks_df.filter(col("passed") == True).count()
    failed_checks = total_checks - passed_checks
    pass_rate = (passed_checks / total_checks * 100) if total_checks > 0 else 0
    
    # Critical failures
    critical_failures = checks_df.filter(
        (col("passed") == False) & (col("severity") == "critical")
    ).count()
    
    # By table summary
    table_summary = checks_df.groupBy("table_name").agg(
        count("*").alias("total_checks"),
        sum(when(col("passed"), 1).otherwise(0)).alias("passed"),
        sum(when(~col("passed"), 1).otherwise(0)).alias("failed")
    ).withColumn("pass_rate", round((col("passed") / col("total_checks")) * 100, 2))
    
    print(f"\n{'='*60}")
    print(f"DATA QUALITY SUMMARY - {execution_date}")
    print(f"{'='*60}")
    print(f"Total Checks: {total_checks}")
    print(f"Passed: {passed_checks} ({pass_rate:.1f}%)")
    print(f"Failed: {failed_checks}")
    print(f"Critical Failures: {critical_failures}")
    print(f"{'='*60}")
    print("\nBy Table:")
    table_summary.show(truncate=False)
    
    # Quality score
    quality_score = pass_rate
    status = "PASS" if quality_score >= 95 and critical_failures == 0 else \
             "WARNING" if quality_score >= 90 else "FAIL"
    
    print(f"\nOverall Quality Score: {quality_score:.1f}% - {status}")
    print(f"{'='*60}")
    
    return {
        "total_checks": total_checks,
        "passed": passed_checks,
        "failed": failed_checks,
        "critical_failures": critical_failures,
        "quality_score": quality_score,
        "status": status
    }

summary = generate_quality_report()

# COMMAND ----------

# DBTITLE 1,Create Quality Score Trend Table
spark.sql("""
    CREATE TABLE IF NOT EXISTS monitoring.quality_score_daily (
        execution_date STRING,
        total_checks INT,
        passed_checks INT,
        failed_checks INT,
        critical_failures INT,
        quality_score DECIMAL(5,2),
        status STRING,
        recorded_at TIMESTAMP
    ) USING DELTA
    LOCATION 'abfss://monitoring@smartretailstore.dfs.core.windows.net/quality_score_daily'
""")

# Insert today's score
trend_entry = spark.createDataFrame([{
    "execution_date": execution_date,
    "total_checks": summary["total_checks"],
    "passed_checks": summary["passed"],
    "failed_checks": summary["failed"],
    "critical_failures": summary["critical_failures"],
    "quality_score": summary["quality_score"],
    "status": summary["status"],
    "recorded_at": datetime.now()
}])

trend_entry.write.format("delta").mode("append").saveAsTable("monitoring.quality_score_daily")

# COMMAND ----------

# DBTITLE 1,Alert on Quality Issues
def send_quality_alerts():
    """Send alerts for failed quality checks"""
    
    # Get failed critical and high severity checks
    failed_checks = spark.table("monitoring.data_quality_log").filter(
        (col("execution_date") == execution_date) &
        (col("passed") == False) &
        (col("severity").isin(["critical", "high"]))
    ).select("table_name", "check_name", "severity", "actual_value").collect()
    
    if failed_checks:
        alerts = []
        for row in failed_checks:
            alerts.append(f"• {row.table_name}.{row.check_name}: {row.actual_value} ({row.severity})")
        
        alert_message = f"""
🚨 Data Quality Alerts - {execution_date}

{chr(10).join(alerts)}

Please review the data quality dashboard for details.
"""
        print(alert_message)
        
        # Log alert
        log_quality_check(
            table_name="monitoring",
            check_name="quality_alert_sent",
            check_type="alert",
            passed=True,
            expected="0 critical issues",
            actual=f"{len(failed_checks)} critical issues",
            severity="high",
            details=alert_message
        )
        
        return True
    
    return False

alert_sent = send_quality_alerts()

# COMMAND ----------

# DBTITLE 1,Summary
all_passed = all(quality_results)
print(f"\n{'='*60}")
print(f"DATA QUALITY MONITORING COMPLETE")
print(f"{'='*60}")
print(f"Execution Date: {execution_date}")
print(f"Checks Run: {len(quality_results)}")
print(f"All Passed: {all_passed}")
print(f"Quality Score: {summary['quality_score']:.1f}%")
print(f"Status: {summary['status']}")
print(f"Alerts Sent: {alert_sent}")
print(f"{'='*60}")

# Return
dbutils.notebook.exit({
    "status": "success" if summary["status"] != "FAIL" else "quality_failed",
    "quality_score": summary["quality_score"],
    "all_passed": all_passed,
    "critical_failures": summary["critical_failures"],
    "total_checks": summary["total_checks"]
})
