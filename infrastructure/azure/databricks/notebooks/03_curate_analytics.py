# Databricks notebook source
# MAGIC %md
# MAGIC # Smart Retail: Curated Analytics Layer
# MAGIC 
# MAGIC Creates analytics-ready datasets:
# MAGIC - Sales aggregations (daily/weekly/monthly)
# MAGIC - Customer 360 with RFM analysis
# MAGIC - Inventory analytics
# MAGIC - Anomaly detection features
# MAGIC 
# MAGIC ## Parameters
# MAGIC - `staging_path`: ADLS staging layer path
# MAGIC - `curated_path`: ADLS curated layer path

# COMMAND ----------

# DBTITLE 1,Initialize
from pyspark.sql import SparkSession
from pyspark.sql.functions import *
from pyspark.sql.window import Window
from delta.tables import DeltaTable
from datetime import date, datetime, timedelta

dbutils.widgets.text("staging_path", "abfss://staging@smartretailstore.dfs.core.windows.net", "Staging Path")
dbutils.widgets.text("curated_path", "abfss://curated@smartretailstore.dfs.core.windows.net", "Curated Path")
dbutils.widgets.text("execution_date", date.today().isoformat(), "Execution Date")

staging_path = dbutils.widgets.get("staging_path")
curated_path = dbutils.widgets.get("curated_path")
execution_date = dbutils.widgets.get("execution_date")

print(f"Staging: {staging_path}")
print(f"Curated: {curated_path}")

# COMMAND ----------

# DBTITLE 1,Create Daily Sales Summary
def create_daily_sales_summary():
    """Create daily sales aggregations"""
    print("Creating daily sales summary...")
    
    orders = spark.read.format("delta").load(f"{staging_path}/fact_orders")
    items = spark.read.format("delta").load(f"{staging_path}/fact_order_items")
    
    # Daily metrics
    daily_sales = orders.groupBy("created_at").agg(
        count("*").alias("total_orders"),
        sum("total_amount").alias("total_revenue"),
        avg("total_amount").alias("avg_order_value"),
        sum("distinct_products").alias("total_items"),
        countDistinct("user_id").alias("unique_customers"),
        count(when(col("status") == "Delivered", 1)).alias("delivered_orders"),
        count(when(col("status") == "Cancelled", 1)).alias("cancelled_orders")
    )
    
    # Calculate cancellation rate
    daily_sales = daily_sales.withColumn(
        "cancellation_rate",
        round((col("cancelled_orders") / col("total_orders")) * 100, 2)
    )
    
    # Profit from items
    daily_profit = items.groupBy("created_at").agg(
        sum("line_revenue").alias("item_revenue"),
        sum("line_profit").alias("total_profit"),
        avg("profit_margin").alias("avg_profit_margin")
    )
    
    daily_sales = daily_sales.join(daily_profit, "created_at", "left")
    
    # Add date dimensions
    daily_sales = daily_sales.withColumn("year", year("created_at")) \
                             .withColumn("month", month("created_at")) \
                             .withColumn("week", weekofyear("created_at")) \
                             .withColumn("weekday", dayofweek("created_at")) \
                             .withColumn("is_weekend", col("weekday").isin([1, 7])) \
                             .withColumn("quarter", quarter("created_at"))
    
    # Add YoY comparison columns (null for now, would need historical data)
    daily_sales = daily_sales.withColumn("revenue_vs_yesterday", lit(None).cast("double")) \
                             .withColumn("orders_vs_yesterday", lit(None).cast("double"))
    
    # Write to curated
    output = f"{curated_path}/sales_daily"
    daily_sales.write \
        .format("delta") \
        .mode("overwrite") \
        .option("overwriteSchema", "true") \
        .save(output)
    
    # Optimize
    spark.sql(f"OPTIMIZE delta.`{output}` ZORDER BY (created_at)")
    
    # Create table
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS curated.sales_daily
        USING DELTA
        LOCATION '{output}'
    """)
    
    count = daily_sales.count()
    total_revenue = daily_sales.select(sum("total_revenue")).collect()[0][0]
    print(f"Created {count} daily sales records, Total Revenue: ₹{total_revenue:,.2f}")
    return count, total_revenue

# COMMAND ----------

# DBTITLE 1,Create Weekly Sales Summary
def create_weekly_sales_summary():
    """Create weekly sales aggregations"""
    print("Creating weekly sales summary...")
    
    orders = spark.read.format("delta").load(f"{staging_path}/fact_orders")
    
    weekly_sales = orders.withColumn("year", year("created_at")) \
                         .withColumn("week", weekofyear("created_at")) \
                         .withColumn("year_week", concat(col("year"), lit("-W"), col("week"))) \
                         .groupBy("year", "week", "year_week").agg(
        count("*").alias("total_orders"),
        sum("total_amount").alias("total_revenue"),
        avg("total_amount").alias("avg_order_value"),
        min("created_at").alias("week_start"),
        max("created_at").alias("week_end"),
        countDistinct("user_id").alias("unique_customers")
    )
    
    # Calculate week-over-week growth
    window_spec = Window.orderBy("year", "week")
    weekly_sales = weekly_sales.withColumn(
        "wow_revenue_growth",
        round(((col("total_revenue") - lag("total_revenue", 1).over(window_spec)) / 
               lag("total_revenue", 1).over(window_spec)) * 100, 2)
    )
    
    output = f"{curated_path}/sales_weekly"
    weekly_sales.write.format("delta").mode("overwrite").save(output)
    
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS curated.sales_weekly
        USING DELTA
        LOCATION '{output}'
    """)
    
    count = weekly_sales.count()
    print(f"Created {count} weekly sales records")
    return count

# COMMAND ----------

# DBTITLE 1,Create Monthly Sales Summary
def create_monthly_sales_summary():
    """Create monthly sales aggregations"""
    print("Creating monthly sales summary...")
    
    orders = spark.read.format("delta").load(f"{staging_path}/fact_orders")
    
    monthly_sales = orders.withColumn("year", year("created_at")) \
                          .withColumn("month", month("created_at")) \
                          .withColumn("year_month", concat(col("year"), lit("-"), col("month"))) \
                          .groupBy("year", "month", "year_month").agg(
        count("*").alias("total_orders"),
        sum("total_amount").alias("total_revenue"),
        avg("total_amount").alias("avg_order_value"),
        countDistinct("user_id").alias("unique_customers"),
        min("created_at").alias("month_start"),
        max("created_at").alias("month_end")
    )
    
    # Calculate MoM growth
    window_spec = Window.orderBy("year", "month")
    monthly_sales = monthly_sales.withColumn(
        "mom_revenue_growth",
        round(((col("total_revenue") - lag("total_revenue", 1).over(window_spec)) / 
               lag("total_revenue", 1).over(window_spec)) * 100, 2)
    )
    
    output = f"{curated_path}/sales_monthly"
    monthly_sales.write.format("delta").mode("overwrite").save(output)
    
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS curated.sales_monthly
        USING DELTA
        LOCATION '{output}'
    """)
    
    count = monthly_sales.count()
    print(f"Created {count} monthly sales records")
    return count

# COMMAND ----------

# DBTITLE 1,Create Customer 360 (RFM Analysis)
def create_customer_360():
    """Create unified customer profile with RFM analysis"""
    print("Creating Customer 360...")
    
    customers = spark.read.format("delta").load(f"{staging_path}/dim_customers")
    orders = spark.read.format("delta").load(f"{staging_path}/fact_orders")
    items = spark.read.format("delta").load(f"{staging_path}/fact_order_items")
    
    # Calculate RFM metrics
    reference_date = current_date()
    
    customer_metrics = orders.groupBy("user_id").agg(
        count("*").alias("frequency"),
        sum("total_amount").alias("monetary"),
        max("created_at").alias("last_order_date")
    )
    
    # Calculate recency (days since last order)
    customer_metrics = customer_metrics.withColumn(
        "recency",
        datediff(reference_date, col("last_order_date"))
    )
    
    # RFM Scoring (1-5 scale)
    recency_quantiles = customer_metrics.approxQuantile("recency", [0.2, 0.4, 0.6, 0.8], 0.01)
    freq_quantiles = customer_metrics.approxQuantile("frequency", [0.2, 0.4, 0.6, 0.8], 0.01)
    monetary_quantiles = customer_metrics.approxQuantile("monetary", [0.2, 0.4, 0.6, 0.8], 0.01)
    
    # R score (lower recency = higher score)
    customer_metrics = customer_metrics.withColumn("r_score",
        when(col("recency") <= recency_quantiles[0], 5)
        .when(col("recency") <= recency_quantiles[1], 4)
        .when(col("recency") <= recency_quantiles[2], 3)
        .when(col("recency") <= recency_quantiles[3], 2)
        .otherwise(1)
    )
    
    # F score
    customer_metrics = customer_metrics.withColumn("f_score",
        when(col("frequency") >= freq_quantiles[3], 5)
        .when(col("frequency") >= freq_quantiles[2], 4)
        .when(col("frequency") >= freq_quantiles[1], 3)
        .when(col("frequency") >= freq_quantiles[0], 2)
        .otherwise(1)
    )
    
    # M score
    customer_metrics = customer_metrics.withColumn("m_score",
        when(col("monetary") >= monetary_quantiles[3], 5)
        .when(col("monetary") >= monetary_quantiles[2], 4)
        .when(col("monetary") >= monetary_quantiles[1], 3)
        .when(col("monetary") >= monetary_quantiles[0], 2)
        .otherwise(1)
    )
    
    # Combined RFM score
    customer_metrics = customer_metrics.withColumn(
        "rfm_score",
        concat(col("r_score"), col("f_score"), col("m_score"))
    ).withColumn(
        "rfm_segment",
        when((col("r_score") >= 4) & (col("f_score") >= 4) & (col("m_score") >= 4), "Champions")
        .when((col("r_score") >= 3) & (col("f_score") >= 3) & (col("m_score") >= 3), "Loyal Customers")
        .when((col("r_score") >= 4) & (col("f_score") <= 2), "New Customers")
        .when((col("r_score") <= 2) & (col("f_score") >= 3), "At Risk")
        .when((col("r_score") <= 2) & (col("f_score") <= 2), "Lost Customers")
        .otherwise("Potential Loyalists")
    )
    
    # Calculate category preferences
    category_prefs = items.join(
        orders.select("id", "user_id").withColumnRenamed("id", "order_id"),
        "order_id"
    ).groupBy("user_id", "category").agg(
        sum("quantity").alias("items_bought")
    )
    
    # Get top category for each customer
    window = Window.partitionBy("user_id").orderBy(desc("items_bought"))
    top_category = category_prefs.withColumn("rank", row_number().over(window)) \
                                  .filter(col("rank") == 1) \
                                  .select("user_id", "category").withColumnRenamed("category", "favorite_category")
    
    # Join everything
    customer_360 = customers.join(
        customer_metrics,
        customers.id == customer_metrics.user_id,
        "left"
    ).join(
        top_category,
        customers.id == top_category.user_id,
        "left"
    ).select(
        customers["*"],
        customer_metrics.recency,
        customer_metrics.frequency,
        customer_metrics.monetary,
        customer_metrics.r_score,
        customer_metrics.f_score,
        customer_metrics.m_score,
        customer_metrics.rfm_score,
        customer_metrics.rfm_segment,
        top_category.favorite_category
    )
    
    # Churn risk prediction
    customer_360 = customer_360.withColumn("churn_risk_score",
        when(col("recency") > 60, 0.9)
        .when(col("recency") > 30, 0.6)
        .when(col("rfm_segment").isin(["At Risk", "Lost Customers"]), 0.8)
        .otherwise(0.1)
    ).withColumn("churn_risk_segment",
        when(col("churn_risk_score") >= 0.7, "High Risk")
        .when(col("churn_risk_score") >= 0.4, "Medium Risk")
        .otherwise("Low Risk")
    )
    
    # Write to curated
    output = f"{curated_path}/customer_360"
    customer_360.write \
        .format("delta") \
        .mode("overwrite") \
        .option("overwriteSchema", "true") \
        .save(output)
    
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS curated.customer_360
        USING DELTA
        LOCATION '{output}'
    """)
    
    count = customer_360.count()
    vip_count = customer_360.filter(col("rfm_segment") == "Champions").count()
    high_risk = customer_360.filter(col("churn_risk_segment") == "High Risk").count()
    print(f"Created {count} customer profiles ({vip_count} Champions, {high_risk} High Risk)")
    return count, vip_count, high_risk

# COMMAND ----------

# DBTITLE 1,Create Inventory Analytics
def create_inventory_analytics():
    """Create inventory metrics and predictions"""
    print("Creating inventory analytics...")
    
    products = spark.read.format("delta").load(f"{staging_path}/dim_products")
    items = spark.read.format("delta").load(f"{staging_path}/fact_order_items")
    
    # Calculate sales velocity (units sold per day)
    sales_velocity = items.groupBy("product_id").agg(
        sum("quantity").alias("total_sold"),
        countDistinct("created_at").alias("selling_days"),
        max("created_at").alias("last_sold_date")
    ).withColumn("daily_velocity",
        col("total_sold") / greatest(col("selling_days"), lit(1))
    )
    
    # Days of inventory remaining
    inventory_metrics = products.join(
        sales_velocity,
        products.id == sales_velocity.product_id,
        "left"
    ).select(
        products["*"],
        coalesce(sales_velocity.total_sold, lit(0)).alias("total_sold"),
        coalesce(sales_velocity.daily_velocity, lit(0)).alias("daily_velocity"),
        sales_velocity.last_sold_date
    ).withColumn("days_of_inventory",
        when(col("daily_velocity") > 0, col("stock") / col("daily_velocity"))
        .otherwise(lit(999))
    )
    
    # Stock alerts
    inventory_metrics = inventory_metrics.withColumn("stock_alert",
        when(col("stock") == 0, "OUT_OF_STOCK")
        .when(col("days_of_inventory") < 7, "CRITICAL")
        .when(col("days_of_inventory") < 14, "LOW")
        .when(col("days_of_inventory") < 30, "MODERATE")
        .otherwise("HEALTHY")
    )
    
    # ABC Analysis (80/20 rule)
    window = Window.orderBy(desc("total_revenue"))
    inventory_metrics = inventory_metrics.withColumn("cumulative_revenue_pct",
        sum("total_revenue").over(window) / sum("total_revenue").over(Window.rowsBetween(Window.unboundedPreceding, Window.unboundedFollowing))
    ).withColumn("abc_classification",
        when(col("cumulative_revenue_pct") <= 0.8, "A")
        .when(col("cumulative_revenue_pct") <= 0.95, "B")
        .otherwise("C")
    )
    
    # Reorder recommendations
    inventory_metrics = inventory_metrics.withColumn("reorder_recommended",
        (col("stock_alert").isin(["OUT_OF_STOCK", "CRITICAL", "LOW"])) |
        (col("stock") < (col("daily_velocity") * 30))
    ).withColumn("suggested_reorder_qty",
        when(col("reorder_recommended"), 
             (col("daily_velocity") * 60 - col("stock")).cast("int"))
        .otherwise(lit(0))
    )
    
    output = f"{curated_path}/inventory_analytics"
    inventory_metrics.write \
        .format("delta") \
        .mode("overwrite") \
        .option("overwriteSchema", "true") \
        .save(output)
    
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS curated.inventory_analytics
        USING DELTA
        LOCATION '{output}'
    """)
    
    count = inventory_metrics.count()
    critical = inventory_metrics.filter(col("stock_alert") == "CRITICAL").count()
    reorder = inventory_metrics.filter(col("reorder_recommended") == True).count()
    print(f"Created {count} inventory records ({critical} critical, {reorder} need reorder)")
    return count, critical, reorder

# COMMAND ----------

# DBTITLE 1,Create Anomaly Detection Features
def create_anomaly_features():
    """Create features for anomaly detection"""
    print("Creating anomaly detection features...")
    
    # Daily metrics with statistical features
    daily_sales = spark.read.format("delta").load(f"{curated_path}/sales_daily")
    
    # Calculate rolling statistics
    window_7d = Window.orderBy("created_at").rowsBetween(-6, 0)
    window_30d = Window.orderBy("created_at").rowsBetween(-29, 0)
    
    anomaly_features = daily_sales.withColumn("revenue_7d_avg", avg("total_revenue").over(window_7d)) \
                                   .withColumn("revenue_7d_std", stddev("total_revenue").over(window_7d)) \
                                   .withColumn("revenue_30d_avg", avg("total_revenue").over(window_30d)) \
                                   .withColumn("orders_7d_avg", avg("total_orders").over(window_7d)) \
                                   .withColumn("orders_7d_std", stddev("total_orders").over(window_7d))
    
    # Z-scores for anomaly detection
    anomaly_features = anomaly_features.withColumn("revenue_zscore",
        (col("total_revenue") - col("revenue_7d_avg")) / greatest(col("revenue_7d_std"), lit(0.01))
    ).withColumn("orders_zscore",
        (col("total_orders") - col("orders_7d_avg")) / greatest(col("orders_7d_std"), lit(0.01))
    )
    
    # Anomaly flags
    threshold = 2.5  # Standard deviations
    anomaly_features = anomaly_features.withColumn("is_revenue_anomaly",
        abs(col("revenue_zscore")) > threshold
    ).withColumn("is_orders_anomaly",
        abs(col("orders_zscore")) > threshold
    ).withColumn("is_any_anomaly",
        col("is_revenue_anomaly") | col("is_orders_anomaly")
    )
    
    # Add trend features
    prev_day = Window.orderBy("created_at")
    anomaly_features = anomaly_features.withColumn("revenue_change_pct",
        ((col("total_revenue") - lag("total_revenue", 1).over(prev_day)) / 
         lag("total_revenue", 1).over(prev_day)) * 100
    )
    
    output = f"{curated_path}/anomaly_features"
    anomaly_features.write \
        .format("delta") \
        .mode("overwrite") \
        .option("overwriteSchema", "true") \
        .save(output)
    
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS curated.anomaly_features
        USING DELTA
        LOCATION '{output}'
    """)
    
    count = anomaly_features.count()
    anomalies = anomaly_features.filter(col("is_any_anomaly") == True).count()
    print(f"Created {count} anomaly feature records ({anomalies} flagged)")
    return count, anomalies

# COMMAND ----------

# DBTITLE 1,Create Product Performance Summary
def create_product_performance():
    """Create product-level performance metrics"""
    print("Creating product performance summary...")
    
    products = spark.read.format("delta").load(f"{staging_path}/dim_products")
    items = spark.read.format("delta").load(f"{staging_path}/fact_order_items")
    
    # Product performance metrics
    performance = items.groupBy("product_id").agg(
        sum("quantity").alias("units_sold"),
        sum("line_revenue").alias("total_revenue"),
        sum("line_profit").alias("total_profit"),
        avg("unit_price").alias("avg_selling_price"),
        countDistinct("order_id").alias("orders_count"),
        min("created_at").alias("first_sale"),
        max("created_at").alias("last_sale")
    )
    
    # Join with product details
    product_perf = products.join(performance, products.id == performance.product_id, "left").select(
        products["*"],
        coalesce(performance.units_sold, lit(0)).alias("units_sold"),
        coalesce(performance.total_revenue, lit(0.0)).alias("total_revenue"),
        coalesce(performance.total_profit, lit(0.0)).alias("total_profit"),
        coalesce(performance.orders_count, lit(0)).alias("orders_count"),
        performance.first_sale,
        performance.last_sale
    )
    
    # Performance scoring
    product_perf = product_perf.withColumn("profit_margin_pct",
        when(col("total_revenue") > 0, (col("total_profit") / col("total_revenue")) * 100)
        .otherwise(0)
    ).withColumn("performance_tier",
        when((col("total_revenue") > 50000) & (col("profit_margin_pct") > 30), "Star")
        .when((col("total_revenue") > 20000) & (col("profit_margin_pct") > 20), "Strong")
        .when(col("total_revenue") > 5000, "Average")
        .when(col("units_sold") > 0, "Weak")
        .otherwise("No Sales")
    )
    
    output = f"{curated_path}/product_performance"
    product_perf.write \
        .format("delta") \
        .mode("overwrite") \
        .option("overwriteSchema", "true") \
        .save(output)
    
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS curated.product_performance
        USING DELTA
        LOCATION '{output}'
    """)
    
    count = product_perf.count()
    stars = product_perf.filter(col("performance_tier") == "Star").count()
    print(f"Created {count} product performance records ({stars} stars)")
    return count, stars

# COMMAND ----------

# DBTITLE 1,Execute Curations
results = {
    "daily_sales": create_daily_sales_summary(),
    "weekly_sales": create_weekly_sales_summary(),
    "monthly_sales": create_monthly_sales_summary(),
    "customer_360": create_customer_360(),
    "inventory": create_inventory_analytics(),
    "anomaly": create_anomaly_features(),
    "product_perf": create_product_performance()
}

# COMMAND ----------

# DBTITLE 1,Optimize All Curated Tables
print("Optimizing curated tables...")
for table in ["sales_daily", "sales_weekly", "sales_monthly", "customer_360", 
              "inventory_analytics", "anomaly_features", "product_performance"]:
    try:
        spark.sql(f"OPTIMIZE curated.{table}")
        spark.sql(f"VACUUM curated.{table} RETAIN 168 HOURS")
        print(f"Optimized curated.{table}")
    except Exception as e:
        print(f"Warning optimizing {table}: {e}")

# COMMAND ----------

# DBTITLE 1,Summary
print(f"\n{'='*60}")
print(f"CURATED LAYER CREATION COMPLETE")
print(f"{'='*60}")
print(f"Daily Sales: {results['daily_sales'][0]} days, ₹{results['daily_sales'][1]:,.2f}")
print(f"Weekly Sales: {results['weekly_sales']} weeks")
print(f"Monthly Sales: {results['monthly_sales']} months")
print(f"Customer 360: {results['customer_360'][0]} profiles ({results['customer_360'][1]} VIP, {results['customer_360'][2]} High Risk)")
print(f"Inventory: {results['inventory'][0]} products ({results['inventory'][1]} critical, {results['inventory'][2]} reorder)")
print(f"Anomaly Features: {results['anomaly'][0]} records ({results['anomaly'][1]} flagged)")
print(f"Product Performance: {results['product_perf'][0]} products ({results['product_perf'][1]} stars)")
print(f"{'='*60}")

# Return
dbutils.notebook.exit({
    "status": "success",
    "tables_created": 7,
    "total_records": sum([results["daily_sales"][0], results["weekly_sales"], results["monthly_sales"], 
                          results["customer_360"][0], results["inventory"][0]])
})
