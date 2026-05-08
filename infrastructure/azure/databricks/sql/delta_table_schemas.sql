-- ============================================================================
-- Smart Retail Delta Lake Table Schemas
-- ============================================================================
-- This file contains the SQL DDL statements for creating Delta Lake tables
-- in the Medallion Architecture (Raw → Staging → Curated)
-- ============================================================================

-- ============================================================================
-- RAW LAYER (Bronze)
-- ============================================================================
-- Raw layer contains unmodified data from source systems

-- Drop and create raw database
DROP DATABASE IF EXISTS raw CASCADE;
CREATE DATABASE IF NOT EXISTS raw;

-- Raw: Users (from SQLite users table)
CREATE TABLE IF NOT EXISTS raw.users (
    id BIGINT,
    name STRING,
    email STRING,
    phone STRING,
    password_hash STRING,
    is_admin BOOLEAN,
    created_at DATE,
    _ingestion_timestamp TIMESTAMP,
    _execution_date STRING
) USING DELTA
PARTITIONED BY (created_at)
LOCATION 'abfss://raw@smartretailstore.dfs.core.windows.net/users';

-- Raw: Products
CREATE TABLE IF NOT EXISTS raw.products (
    id BIGINT,
    sku STRING,
    name STRING,
    category STRING,
    description STRING,
    price DECIMAL(10,2),
    stock INT,
    image STRING,
    sizes STRING,
    created_at DATE,
    _ingestion_timestamp TIMESTAMP,
    _execution_date STRING
) USING DELTA
PARTITIONED BY (category)
LOCATION 'abfss://raw@smartretailstore.dfs.core.windows.net/products';

-- Raw: Orders
CREATE TABLE IF NOT EXISTS raw.orders (
    id BIGINT,
    order_number STRING,
    user_id BIGINT,
    customer_name STRING,
    phone STRING,
    address STRING,
    city STRING,
    state STRING,
    pincode STRING,
    status STRING,
    tracking_id STRING,
    total_amount DECIMAL(10,2),
    payment_method STRING,
    payment_status STRING,
    cancel_reason STRING,
    return_status STRING,
    created_at DATE,
    _ingestion_timestamp TIMESTAMP,
    _execution_date STRING
) USING DELTA
PARTITIONED BY (created_at)
LOCATION 'abfss://raw@smartretailstore.dfs.core.windows.net/orders';

-- Raw: Order Items
CREATE TABLE IF NOT EXISTS raw.order_items (
    id BIGINT,
    order_id BIGINT,
    product_id BIGINT,
    product_name STRING,
    size STRING,
    quantity INT,
    unit_price DECIMAL(10,2),
    _ingestion_timestamp TIMESTAMP,
    _execution_date STRING
) USING DELTA
LOCATION 'abfss://raw@smartretailstore.dfs.core.windows.net/order_items';

-- Raw: Support Tickets
CREATE TABLE IF NOT EXISTS raw.support_tickets (
    id BIGINT,
    ticket_number STRING,
    customer_email STRING,
    subject STRING,
    issue STRING,
    order_number STRING,
    status STRING,
    priority STRING,
    source STRING,
    sentiment STRING,
    created_at DATE,
    _ingestion_timestamp TIMESTAMP,
    _execution_date STRING
) USING DELTA
PARTITIONED BY (created_at)
LOCATION 'abfss://raw@smartretailstore.dfs.core.windows.net/support_tickets';

-- ============================================================================
-- STAGING LAYER (Silver)
-- ============================================================================
-- Staging layer contains cleaned, deduplicated data with SCD Type 2 dimensions

DROP DATABASE IF EXISTS staging CASCADE;
CREATE DATABASE IF NOT EXISTS staging;

-- Staging: Dimension Customers (SCD Type 2)
CREATE TABLE IF NOT EXISTS staging.dim_customers (
    id BIGINT,
    name STRING,
    email STRING,
    phone STRING,
    is_admin BOOLEAN,
    created_at DATE,
    -- Customer metrics
    total_orders BIGINT,
    total_spent DECIMAL(12,2),
    avg_order_value DECIMAL(10,2),
    last_order_date DATE,
    customer_segment STRING,
    -- SCD Type 2 columns
    effective_date DATE,
    expiration_date DATE,
    is_current BOOLEAN,
    -- Metadata
    _ingestion_timestamp TIMESTAMP,
    _execution_date STRING
) USING DELTA
PARTITIONED BY (customer_segment)
LOCATION 'abfss://staging@smartretailstore.dfs.core.windows.net/dim_customers';

-- Staging: Dimension Products (SCD Type 2)
CREATE TABLE IF NOT EXISTS staging.dim_products (
    id BIGINT,
    sku STRING,
    name STRING,
    category STRING,
    description STRING,
    price DECIMAL(10,2),
    stock INT,
    image STRING,
    sizes STRING,
    created_at DATE,
    -- Product metrics
    total_sold BIGINT,
    total_revenue DECIMAL(12,2),
    inventory_value DECIMAL(12,2),
    stock_status STRING,
    product_performance STRING,
    -- SCD Type 2 columns
    effective_date DATE,
    expiration_date DATE,
    is_current BOOLEAN,
    -- Metadata
    _ingestion_timestamp TIMESTAMP,
    _execution_date STRING
) USING DELTA
PARTITIONED BY (category)
LOCATION 'abfss://staging@smartretailstore.dfs.core.windows.net/dim_products';

-- Staging: Fact Orders
CREATE TABLE IF NOT EXISTS staging.fact_orders (
    id BIGINT,
    order_number STRING,
    user_id BIGINT,
    customer_name STRING,
    status STRING,
    total_amount DECIMAL(10,2),
    payment_method STRING,
    created_at DATE,
    -- Order metrics
    total_items BIGINT,
    distinct_products BIGINT,
    -- Date dimensions
    order_year INT,
    order_month INT,
    order_day INT,
    order_weekday INT,
    order_quarter INT,
    is_weekend BOOLEAN,
    -- SLA
    expected_delivery_days INT,
    -- Metadata
    _ingestion_timestamp TIMESTAMP,
    _execution_date STRING
) USING DELTA
PARTITIONED BY (order_year, order_month)
LOCATION 'abfss://staging@smartretailstore.dfs.core.windows.net/fact_orders';

-- Staging: Fact Order Items
CREATE TABLE IF NOT EXISTS staging.fact_order_items (
    id BIGINT,
    order_id BIGINT,
    product_id BIGINT,
    product_name STRING,
    category STRING,
    size STRING,
    quantity INT,
    unit_price DECIMAL(10,2),
    -- Profit calculations
    unit_cost DECIMAL(10,2),
    line_revenue DECIMAL(10,2),
    line_cost DECIMAL(10,2),
    line_profit DECIMAL(10,2),
    profit_margin DECIMAL(5,2),
    -- Date reference
    created_at DATE,
    order_status STRING,
    -- Metadata
    _ingestion_timestamp TIMESTAMP,
    _execution_date STRING
) USING DELTA
PARTITIONED BY (created_at)
LOCATION 'abfss://staging@smartretailstore.dfs.core.windows.net/fact_order_items';

-- Staging: Fact Support Tickets
CREATE TABLE IF NOT EXISTS staging.fact_support_tickets (
    id BIGINT,
    ticket_number STRING,
    customer_email STRING,
    subject STRING,
    status STRING,
    priority STRING,
    source STRING,
    sentiment STRING,
    created_at DATE,
    -- Resolution metrics
    resolution_days DOUBLE,
    severity_score INT,
    requires_followup BOOLEAN,
    -- Metadata
    _ingestion_timestamp TIMESTAMP,
    _execution_date STRING
) USING DELTA
PARTITIONED BY (created_at)
LOCATION 'abfss://staging@smartretailstore.dfs.core.windows.net/fact_support_tickets';

-- ============================================================================
-- CURATED LAYER (Gold)
-- ============================================================================
-- Curated layer contains analytics-ready aggregations and business metrics

DROP DATABASE IF EXISTS curated CASCADE;
CREATE DATABASE IF NOT EXISTS curated;

-- Curated: Daily Sales Summary
CREATE TABLE IF NOT EXISTS curated.sales_daily (
    created_at DATE,
    total_orders BIGINT,
    total_revenue DECIMAL(12,2),
    avg_order_value DECIMAL(10,2),
    total_items BIGINT,
    unique_customers BIGINT,
    delivered_orders BIGINT,
    cancelled_orders BIGINT,
    cancellation_rate DECIMAL(5,2),
    -- Profit
    item_revenue DECIMAL(12,2),
    total_profit DECIMAL(12,2),
    avg_profit_margin DECIMAL(5,2),
    -- Date dimensions
    year INT,
    month INT,
    week INT,
    weekday INT,
    is_weekend BOOLEAN,
    quarter INT,
    -- Comparisons
    revenue_vs_yesterday DECIMAL(5,2),
    orders_vs_yesterday DECIMAL(5,2)
) USING DELTA
PARTITIONED BY (year, month)
LOCATION 'abfss://curated@smartretailstore.dfs.core.windows.net/sales_daily';

-- Curated: Weekly Sales Summary
CREATE TABLE IF NOT EXISTS curated.sales_weekly (
    year INT,
    week INT,
    year_week STRING,
    total_orders BIGINT,
    total_revenue DECIMAL(12,2),
    avg_order_value DECIMAL(10,2),
    week_start DATE,
    week_end DATE,
    unique_customers BIGINT,
    wow_revenue_growth DECIMAL(5,2)
) USING DELTA
LOCATION 'abfss://curated@smartretailstore.dfs.core.windows.net/sales_weekly';

-- Curated: Monthly Sales Summary
CREATE TABLE IF NOT EXISTS curated.sales_monthly (
    year INT,
    month INT,
    year_month STRING,
    total_orders BIGINT,
    total_revenue DECIMAL(12,2),
    avg_order_value DECIMAL(10,2),
    unique_customers BIGINT,
    month_start DATE,
    month_end DATE,
    mom_revenue_growth DECIMAL(5,2)
) USING DELTA
LOCATION 'abfss://curated@smartretailstore.dfs.core.windows.net/sales_monthly';

-- Curated: Customer 360 (RFM Analysis)
CREATE TABLE IF NOT EXISTS curated.customer_360 (
    id BIGINT,
    name STRING,
    email STRING,
    phone STRING,
    is_admin BOOLEAN,
    created_at DATE,
    -- Metrics
    total_orders BIGINT,
    total_spent DECIMAL(12,2),
    avg_order_value DECIMAL(10,2),
    last_order_date DATE,
    customer_segment STRING,
    favorite_category STRING,
    -- RFM
    recency INT,
    frequency BIGINT,
    monetary DECIMAL(12,2),
    r_score INT,
    f_score INT,
    m_score INT,
    rfm_score STRING,
    rfm_segment STRING,
    -- Churn
    churn_risk_score DOUBLE,
    churn_risk_segment STRING,
    -- Metadata
    _ingestion_timestamp TIMESTAMP,
    _execution_date STRING
) USING DELTA
PARTITIONED BY (rfm_segment, churn_risk_segment)
LOCATION 'abfss://curated@smartretailstore.dfs.core.windows.net/customer_360';

-- Curated: Inventory Analytics
CREATE TABLE IF NOT EXISTS curated.inventory_analytics (
    id BIGINT,
    sku STRING,
    name STRING,
    category STRING,
    price DECIMAL(10,2),
    stock INT,
    total_sold BIGINT,
    total_revenue DECIMAL(12,2),
    total_profit DECIMAL(12,2),
    inventory_value DECIMAL(12,2),
    stock_status STRING,
    product_performance STRING,
    -- Velocity metrics
    daily_velocity DOUBLE,
    days_of_inventory DOUBLE,
    last_sold_date DATE,
    -- ABC Analysis
    cumulative_revenue_pct DOUBLE,
    abc_classification STRING,
    -- Reorder
    reorder_recommended BOOLEAN,
    suggested_reorder_qty INT,
    -- Metadata
    _ingestion_timestamp TIMESTAMP,
    _execution_date STRING
) USING DELTA
PARTITIONED BY (category, stock_status)
LOCATION 'abfss://curated@smartretailstore.dfs.core.windows.net/inventory_analytics';

-- Curated: Anomaly Detection Features
CREATE TABLE IF NOT EXISTS curated.anomaly_features (
    created_at DATE,
    total_orders BIGINT,
    total_revenue DECIMAL(12,2),
    avg_order_value DECIMAL(10,2),
    total_items BIGINT,
    unique_customers BIGINT,
    cancellation_rate DECIMAL(5,2),
    -- Rolling statistics
    revenue_7d_avg DOUBLE,
    revenue_7d_std DOUBLE,
    revenue_30d_avg DOUBLE,
    orders_7d_avg DOUBLE,
    orders_7d_std DOUBLE,
    -- Z-scores
    revenue_zscore DOUBLE,
    orders_zscore DOUBLE,
    -- Flags
    is_revenue_anomaly BOOLEAN,
    is_orders_anomaly BOOLEAN,
    is_any_anomaly BOOLEAN,
    -- Trend
    revenue_change_pct DOUBLE,
    -- Date dimensions
    year INT,
    month INT,
    week INT,
    weekday INT,
    is_weekend BOOLEAN,
    quarter INT
) USING DELTA
PARTITIONED BY (year, month)
LOCATION 'abfss://curated@smartretailstore.dfs.core.windows.net/anomaly_features';

-- Curated: Product Performance
CREATE TABLE IF NOT EXISTS curated.product_performance (
    id BIGINT,
    sku STRING,
    name STRING,
    category STRING,
    price DECIMAL(10,2),
    stock INT,
    units_sold BIGINT,
    total_revenue DECIMAL(12,2),
    total_profit DECIMAL(12,2),
    avg_selling_price DECIMAL(10,2),
    orders_count BIGINT,
    first_sale DATE,
    last_sale DATE,
    profit_margin_pct DECIMAL(5,2),
    performance_tier STRING,
    _ingestion_timestamp TIMESTAMP,
    _execution_date STRING
) USING DELTA
PARTITIONED BY (category, performance_tier)
LOCATION 'abfss://curated@smartretailstore.dfs.core.windows.net/product_performance';

-- ============================================================================
-- OPTIMIZATION COMMANDS
-- ============================================================================
-- Run these after initial load to optimize table performance

-- Optimize with Z-Ordering on frequently filtered columns
-- OPTIMIZE curated.sales_daily ZORDER BY (created_at);
-- OPTIMIZE curated.customer_360 ZORDER BY (id);
-- OPTIMIZE curated.inventory_analytics ZORDER BY (id);

-- Vacuum old versions (retain 7 days = 168 hours)
-- VACUUM raw.users RETAIN 168 HOURS;
-- VACUUM staging.dim_customers RETAIN 168 HOURS;
-- VACUUM curated.sales_daily RETAIN 168 HOURS;

-- Compute statistics for query optimization
-- ANALYZE TABLE raw.users COMPUTE STATISTICS;
-- ANALYZE TABLE staging.fact_orders COMPUTE STATISTICS FOR ALL COLUMNS;
-- ANALYZE TABLE curated.sales_daily COMPUTE STATISTICS;

-- ============================================================================
-- VIEWS FOR POWER BI / REPORTING
-- ============================================================================

-- Sales Dashboard View
CREATE OR REPLACE VIEW curated.v_sales_dashboard AS
SELECT 
    d.created_at,
    d.total_orders,
    d.total_revenue,
    d.avg_order_value,
    d.unique_customers,
    d.cancellation_rate,
    d.total_profit,
    d.avg_profit_margin,
    d.year,
    d.month,
    d.is_weekend,
    d.wow_revenue_growth
FROM curated.sales_daily d
ORDER BY d.created_at DESC;

-- Customer Analytics View
CREATE OR REPLACE VIEW curated.v_customer_analytics AS
SELECT 
    c.id,
    c.name,
    c.email,
    c.customer_segment,
    c.rfm_score,
    c.rfm_segment,
    c.recency,
    c.frequency,
    c.monetary,
    c.churn_risk_segment,
    c.total_orders,
    c.total_spent,
    c.favorite_category,
    CASE 
        WHEN c.rfm_segment = 'Champions' THEN 1
        WHEN c.rfm_segment = 'Loyal Customers' THEN 2
        WHEN c.rfm_segment = 'Potential Loyalists' THEN 3
        WHEN c.rfm_segment = 'New Customers' THEN 4
        WHEN c.rfm_segment = 'At Risk' THEN 5
        ELSE 6
    END as segment_priority
FROM curated.customer_360 c;

-- Inventory Status View
CREATE OR REPLACE VIEW curated.v_inventory_status AS
SELECT 
    i.id,
    i.sku,
    i.name,
    i.category,
    i.stock,
    i.stock_status,
    i.total_sold,
    i.days_of_inventory,
    i.abc_classification,
    i.reorder_recommended,
    i.suggested_reorder_qty,
    i.daily_velocity,
    i.inventory_value,
    CASE 
        WHEN i.stock_status = 'OUT_OF_STOCK' THEN 1
        WHEN i.stock_status = 'CRITICAL' THEN 2
        WHEN i.stock_status = 'LOW' THEN 3
        WHEN i.stock_status = 'MODERATE' THEN 4
        ELSE 5
    END as stock_alert_priority
FROM curated.inventory_analytics i;

-- Anomaly Alerts View
CREATE OR REPLACE VIEW curated.v_anomaly_alerts AS
SELECT 
    a.created_at,
    a.total_revenue,
    a.total_orders,
    a.revenue_zscore,
    a.orders_zscore,
    a.is_revenue_anomaly,
    a.is_orders_anomaly,
    a.revenue_change_pct,
    CASE 
        WHEN a.is_revenue_anomaly AND a.revenue_zscore > 0 THEN 'Revenue Spike'
        WHEN a.is_revenue_anomaly AND a.revenue_zscore < 0 THEN 'Revenue Drop'
        WHEN a.is_orders_anomaly AND a.orders_zscore > 0 THEN 'Order Spike'
        WHEN a.is_orders_anomaly AND a.orders_zscore < 0 THEN 'Order Drop'
        ELSE 'Normal'
    END as alert_type,
    CASE 
        WHEN abs(a.revenue_zscore) > 3 OR abs(a.orders_zscore) > 3 THEN 'High'
        WHEN abs(a.revenue_zscore) > 2 OR abs(a.orders_zscore) > 2 THEN 'Medium'
        ELSE 'Low'
    END as severity
FROM curated.anomaly_features a
WHERE a.is_any_anomaly = TRUE
ORDER BY a.created_at DESC;
