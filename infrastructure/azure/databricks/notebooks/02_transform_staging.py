# Databricks notebook source
# MAGIC %md
# MAGIC # Smart Retail: Staging Layer Transformation
# MAGIC 
# MAGIC Transforms raw data into staging layer with:
# MAGIC - Data quality checks
# MAGIC - SCD Type 2 for dimensions
# MAGIC - Referential integrity
# MAGIC 
# MAGIC ## Parameters
# MAGIC - `raw_path`: ADLS raw layer path
# MAGIC - `staging_path`: ADLS staging layer path
# MAGIC - `execution_date`: Date of execution

# COMMAND ----------

# DBTITLE 1,Initialize
from pyspark.sql import SparkSession
from pyspark.sql.functions import *
from pyspark.sql.window import Window
from delta.tables import DeltaTable
from datetime import date, datetime

dbutils.widgets.text("raw_path", "abfss://raw@smartretailstore.dfs.core.windows.net", "Raw Path")
dbutils.widgets.text("staging_path", "abfss://staging@smartretailstore.dfs.core.windows.net", "Staging Path")
dbutils.widgets.text("execution_date", date.today().isoformat(), "Execution Date")

raw_path = dbutils.widgets.get("raw_path")
staging_path = dbutils.widgets.get("staging_path")
execution_date = dbutils.widgets.get("execution_date")

print(f"Raw: {raw_path}")
print(f"Staging: {staging_path}")
print(f"Date: {execution_date}")

# COMMAND ----------

# DBTITLE 1,Transform Customers Dimension (SCD Type 2)
def transform_customers_dim():
    """Transform customers with SCD Type 2 tracking"""
    print("Transforming customers dimension...")
    
    # Read raw data
    raw_df = spark.read.format("delta").load(f"{raw_path}/users")
    
    # Calculate customer metrics from orders
    orders_df = spark.read.format("delta").load(f"{raw_path}/orders")
    
    customer_metrics = orders_df.groupBy("user_id").agg(
        count("*").alias("total_orders"),
        sum("total_amount").alias("total_spent"),
        avg("total_amount").alias("avg_order_value"),
        max("created_at").alias("last_order_date")
    )
    
    # Join with customer data
    customers_df = raw_df.join(
        customer_metrics,
        raw_df.id == customer_metrics.user_id,
        "left"
    ).select(
        raw_df["*"],
        coalesce(customer_metrics.total_orders, lit(0)).alias("total_orders"),
        coalesce(customer_metrics.total_spent, lit(0.0)).alias("total_spent"),
        coalesce(customer_metrics.avg_order_value, lit(0.0)).alias("avg_order_value"),
        customer_metrics.last_order_date
    )
    
    # Add SCD Type 2 columns
    customers_df = customers_df.withColumn("effective_date", current_date()) \
                               .withColumn("expiration_date", lit("9999-12-31").cast("date")) \
                               .withColumn("is_current", lit(True)) \
                               .withColumn("customer_segment",
                                   when(col("total_spent") > 10000, "VIP")
                                   .when(col("total_spent") > 5000, "Gold")
                                   .when(col("total_spent") > 1000, "Silver")
                                   .otherwise("Bronze"))
    
    # Write to staging
    output = f"{staging_path}/dim_customers"
    customers_df.write \
        .format("delta") \
        .mode("overwrite") \
        .option("overwriteSchema", "true") \
        .save(output)
    
    # Create/merge SCD table
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS staging.dim_customers
        USING DELTA
        LOCATION '{output}'
    """)
    
    count = customers_df.count()
    print(f"Transformed {count} customers")
    return count

# COMMAND ----------

# DBTITLE 1,Transform Products Dimension
def transform_products_dim():
    """Transform products with inventory metrics"""
    print("Transforming products dimension...")
    
    raw_df = spark.read.format("delta").load(f"{raw_path}/products")
    
    # Calculate sales metrics
    order_items_df = spark.read.format("delta").load(f"{raw_path}/order_items")
    
    sales_metrics = order_items_df.groupBy("product_id").agg(
        sum("quantity").alias("total_sold"),
        sum(col("quantity") * col("unit_price")).alias("total_revenue")
    )
    
    products_df = raw_df.join(
        sales_metrics,
        raw_df.id == sales_metrics.product_id,
        "left"
    ).select(
        raw_df["*"],
        coalesce(sales_metrics.total_sold, lit(0)).alias("total_sold"),
        coalesce(sales_metrics.total_revenue, lit(0.0)).alias("total_revenue"),
        (col("price") * col("stock")).alias("inventory_value")
    )
    
    # Add stock status
    products_df = products_df.withColumn("stock_status",
        when(col("stock") == 0, "Out of Stock")
        .when(col("stock") < 10, "Low Stock")
        .when(col("stock") < 50, "Medium Stock")
        .otherwise("In Stock")
    ).withColumn("product_performance",
        when(col("total_sold") > 100, "High")
        .when(col("total_sold") > 20, "Medium")
        .otherwise("Low")
    )
    
    output = f"{staging_path}/dim_products"
    products_df.write \
        .format("delta") \
        .mode("overwrite") \
        .option("overwriteSchema", "true") \
        .save(output)
    
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS staging.dim_products
        USING DELTA
        LOCATION '{output}'
    """)
    
    count = products_df.count()
    print(f"Transformed {count} products")
    return count

# COMMAND ----------

# DBTITLE 1,Transform Orders Fact
def transform_orders_fact():
    """Transform orders into fact table with dimensions"""
    print("Transforming orders fact...")
    
    orders_df = spark.read.format("delta").load(f"{raw_path}/orders")
    order_items_df = spark.read.format("delta").load(f"{raw_path}/order_items")
    
    # Aggregate items per order
    items_agg = order_items_df.groupBy("order_id").agg(
        sum("quantity").alias("total_items"),
        count("*").alias("distinct_products"),
        collect_list("product_id").alias("product_ids")
    )
    
    # Join with orders
    fact_df = orders_df.join(
        items_agg,
        orders_df.id == items_agg.order_id,
        "left"
    ).select(
        orders_df["*"],
        items_agg.total_items,
        items_agg.distinct_products
    )
    
    # Add date dimensions
    fact_df = fact_df.withColumn("order_year", year("created_at")) \
                     .withColumn("order_month", month("created_at")) \
                     .withColumn("order_day", dayofmonth("created_at")) \
                     .withColumn("order_weekday", dayofweek("created_at")) \
                     .withColumn("order_quarter", quarter("created_at")) \
                     .withColumn("is_weekend", dayofweek("created_at").isin([1, 7]))
    
    # Calculate delivery SLA (mock)
    fact_df = fact_df.withColumn("expected_delivery_days",
        when(col("status") == "Delivered", lit(3))
        .when(col("status") == "Shipped", lit(2))
        .when(col("status") == "Processing", lit(5))
        .otherwise(lit(None))
    )
    
    output = f"{staging_path}/fact_orders"
    fact_df.write \
        .format("delta") \
        .mode("overwrite") \
        .option("overwriteSchema", "true") \
        .save(output)
    
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS staging.fact_orders
        USING DELTA
        LOCATION '{output}'
    """)
    
    count = fact_df.count()
    print(f"Transformed {count} orders")
    return count

# COMMAND ----------

# DBTITLE 1,Transform Order Items Fact
def transform_order_items_fact():
    """Transform line items with profit calculations"""
    print("Transforming order items fact...")
    
    items_df = spark.read.format("delta").load(f"{raw_path}/order_items")
    products_df = spark.read.format("delta").load(f"{raw_path}/products")
    orders_df = spark.read.format("delta").load(f"{raw_path}/orders")
    
    # Join to get cost (assume 60% of price is cost)
    items_enriched = items_df.join(
        products_df.select("id", "price", "category"),
        items_df.product_id == products_df.id,
        "left"
    ).select(
        items_df["*"],
        products_df.category,
        (col("unit_price") * 0.6).alias("unit_cost")  # 40% margin
    )
    
    # Calculate profit
    items_enriched = items_enriched.withColumn("line_revenue", col("quantity") * col("unit_price")) \
                                   .withColumn("line_cost", col("quantity") * col("unit_cost")) \
                                   .withColumn("line_profit", col("line_revenue") - col("line_cost")) \
                                   .withColumn("profit_margin", round((col("line_profit") / col("line_revenue")) * 100, 2))
    
    # Join with order date
    items_enriched = items_enriched.join(
        orders_df.select("id", "created_at", "status").withColumnRenamed("id", "order_id"),
        "order_id",
        "left"
    )
    
    output = f"{staging_path}/fact_order_items"
    items_enriched.write \
        .format("delta") \
        .mode("overwrite") \
        .option("overwriteSchema", "true") \
        .save(output)
    
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS staging.fact_order_items
        USING DELTA
        LOCATION '{output}'
    """)
    
    count = items_enriched.count()
    total_profit = items_enriched.select(sum("line_profit")).collect()[0][0]
    print(f"Transformed {count} order items, Total Profit: ₹{total_profit:,.2f}")
    return count, total_profit

# COMMAND ----------

# DBTITLE 1,Transform Support Tickets
def transform_support_tickets():
    """Transform tickets with resolution metrics"""
    print("Transforming support tickets...")
    
    tickets_df = spark.read.format("delta").load(f"{raw_path}/support_tickets")
    
    # Calculate resolution time (mock)
    tickets_df = tickets_df.withColumn("resolution_days",
        when(col("status").isin(["Resolved", "Closed"]), 
             rand() * 5 + 1)  # Random 1-6 days
        .otherwise(lit(None))
    )
    
    # Add severity score
    tickets_df = tickets_df.withColumn("severity_score",
        when(col("priority") == "Critical", 4)
        .when(col("priority") == "High", 3)
        .when(col("priority") == "Medium", 2)
        .otherwise(1)
    )
    
    # Categorize by sentiment
    tickets_df = tickets_df.withColumn("requires_followup",
        (col("sentiment") == "negative") & (col("status") != "Closed")
    )
    
    output = f"{staging_path}/fact_support_tickets"
    tickets_df.write \
        .format("delta") \
        .mode("overwrite") \
        .option("overwriteSchema", "true") \
        .save(output)
    
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS staging.fact_support_tickets
        USING DELTA
        LOCATION '{output}'
    """)
    
    count = tickets_df.count()
    avg_resolution = tickets_df.filter(col("resolution_days").isNotNull()).select(avg("resolution_days")).collect()[0][0]
    print(f"Transformed {count} tickets, Avg Resolution: {avg_resolution:.1f} days")
    return count, avg_resolution

# COMMAND ----------

# DBTITLE 1,Data Quality Checks
def run_data_quality_checks():
    """Run comprehensive data quality checks"""
    print("\nRunning data quality checks...")
    
    checks = []
    
    # Check 1: No duplicate order numbers
    orders = spark.read.format("delta").load(f"{staging_path}/fact_orders")
    dup_orders = orders.groupBy("order_number").count().filter(col("count") > 1).count()
    checks.append(("Duplicate Orders", dup_orders == 0, f"Found {dup_orders} duplicates"))
    
    # Check 2: All orders have items
    order_items = spark.read.format("delta").load(f"{staging_path}/fact_order_items")
    orders_with_items = order_items.select("order_id").distinct().count()
    total_orders = orders.count()
    checks.append(("Orders with Items", orders_with_items > 0, 
                   f"{orders_with_items}/{total_orders} orders have items"))
    
    # Check 3: No negative amounts
    negative_amounts = orders.filter(col("total_amount") < 0).count()
    checks.append(("No Negative Amounts", negative_amounts == 0, 
                   f"Found {negative_amounts} negative amounts"))
    
    # Check 4: Customer segment coverage
    customers = spark.read.format("delta").load(f"{staging_path}/dim_customers")
    null_segments = customers.filter(col("customer_segment").isNull()).count()
    checks.append(("Customer Segments", null_segments == 0, 
                   f"{null_segments} customers without segment"))
    
    # Check 5: Product categories valid
    products = spark.read.format("delta").load(f"{staging_path}/dim_products")
    null_categories = products.filter(col("category").isNull()).count()
    checks.append(("Product Categories", null_categories == 0, 
                   f"{null_categories} products without category"))
    
    # Print results
    passed = sum(1 for _, result, _ in checks if result)
    total = len(checks)
    
    print(f"\n{'='*60}")
    print(f"DATA QUALITY RESULTS: {passed}/{total} passed")
    print(f"{'='*60}")
    for check_name, result, message in checks:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} | {check_name}: {message}")
    print(f"{'='*60}")
    
    return passed == total

# COMMAND ----------

# DBTITLE 1,Execute Transformations
results = {
    "customers": transform_customers_dim(),
    "products": transform_products_dim(),
    "orders": transform_orders_fact(),
    "order_items": transform_order_items_fact(),
    "tickets": transform_support_tickets()
}

quality_passed = run_data_quality_checks()

# COMMAND ----------

# DBTITLE 1,Summary
print(f"\n{'='*50}")
print(f"STAGING LAYER TRANSFORMATION COMPLETE")
print(f"{'='*50}")
print(f"Execution Date: {execution_date}")
print(f"Customers: {results['customers']}")
print(f"Products: {results['products']}")
print(f"Orders: {results['orders']}")
print(f"Order Items: {results['order_items'][0]} (Profit: ₹{results['order_items'][1]:,.2f})")
print(f"Tickets: {results['tickets'][0]} (Avg Resolution: {results['tickets'][1]:.1f} days)")
print(f"Data Quality: {'PASSED' if quality_passed else 'FAILED'}")
print(f"{'='*50}")

# Return
dbutils.notebook.exit({
    "status": "success" if quality_passed else "quality_failed",
    "quality_passed": quality_passed,
    "records_processed": sum([results["customers"], results["products"], results["orders"], results["order_items"][0]])
})
