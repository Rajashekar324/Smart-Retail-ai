# Azure Data Engineering Pipeline Setup Guide

## Overview

This guide describes the production-ready data engineering pipeline for Smart Retail AI Store using:

- **Azure Data Factory** - Data orchestration and ingestion
- **Azure Databricks** - Data transformation with PySpark and Delta Lake
- **Azure Data Lake Storage Gen2** - Data lake with Medallion Architecture
- **Microsoft Fabric** - Lakehouse, dataflows, and Data Activator
- **Delta Lake** - ACID transactions, time travel, and scalable metadata

## Architecture: Medallion Pattern

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Data Sources                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│  SQLite Database  │  REST API  │  Streaming Events  │  External Files      │
└────────┬──────────────────────┴────────────────────┴──────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            RAW (Bronze)                                     │
│                      Azure Data Lake Gen2 - raw container                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  raw.users          │  raw.products  │  raw.orders  │  raw.support_tickets   │
│  Format: Delta      │  Parquet       │  JSON        │  Delta                 │
│  Partitioned by date│  Partitioned   │  Batch       │  Partitioned by date   │
└────────┬────────────────────────────────────────────────────────────────────┘
         │
         │  Azure Data Factory → Databricks Notebooks
         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          STAGING (Silver)                                   │
│                    Azure Data Lake Gen2 - staging container                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  staging.dim_customers    │  staging.dim_products    │  staging.fact_orders│
│  SCD Type 2               │  SCD Type 2              │  Enriched facts      │
│  Customer segmentation    │  Stock status, ABC       │  Date dimensions     │
│  RFM scores               │  Inventory metrics       │  Profit calculations │
├─────────────────────────────────────────────────────────────────────────────┤
│  staging.fact_order_items │  staging.fact_support_tickets                  │
│  Line-level profit        │  Sentiment, resolution    │                     │
└────────┬────────────────────────────────────────────────────────────────────┘
         │
         │  Databricks Curation Notebooks
         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          CURATED (Gold)                                     │
│                    Azure Data Lake Gen2 - curated container                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  curated.sales_daily       │  curated.sales_weekly    │  curated.sales_monthly│
│  Daily aggregations         │  WoW growth               │  MoM growth          │
│  Cancellation rates         │  Weekly KPIs              │  Monthly trends      │
├─────────────────────────────────────────────────────────────────────────────┤
│  curated.customer_360       │  curated.inventory_analytics                    │
│  RFM analysis               │  Velocity, ABC classification                   │
│  Churn prediction           │  Reorder recommendations                      │
│  Lifetime value             │  Days of inventory                            │
├─────────────────────────────────────────────────────────────────────────────┤
│  curated.anomaly_features   │  curated.product_performance                    │
│  Z-scores, statistical        │  Profit margins, tiers                          │
│  Anomaly flags              │  Performance scoring                            │
└────────┬────────────────────────────────────────────────────────────────────┘
         │
         │  Dataflows, Power BI, ML Endpoints
         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Consumers                                           │
├─────────────────────────────────────────────────────────────────────────────┤
│  Power BI Reports  │  ML Models  │  Data Activator  │  Analytics API      │
│  Real-time dashboards│  Churn pred │  Alerts         │  REST endpoints      │
└─────────────────────────────────────────────────────────────────────────────┘
```

## File Structure

```
infrastructure/
├── azure/
│   ├── data_factory/
│   │   ├── pipeline_master.json          # Master orchestration pipeline
│   │   ├── pipeline_ingest_raw.json      # Raw layer ingestion
│   │   ├── pipeline_transform.json       # Staging transformations
│   │   └── pipeline_curate.json          # Curated layer creation
│   │
│   ├── databricks/
│   │   ├── notebooks/
│   │   │   ├── 01_ingest_raw.py        # Raw data ingestion
│   │   │   ├── 02_transform_staging.py # SCD Type 2, enrichment
│   │   │   ├── 03_curate_analytics.py  # Aggregations, RFM
│   │   │   └── 04_data_quality_monitoring.py  # Quality checks
│   │   │
│   │   └── sql/
│   │       └── delta_table_schemas.sql   # DDL for all Delta tables
│   │
│   └── fabric/
│       └── lakehouse_config.json         # Microsoft Fabric configuration
│
└── DATA_PIPELINE_SETUP.md               # This documentation
```

## Setup Instructions

### 1. Azure Prerequisites

Create the following Azure resources:

```bash
# Resource Group
az group create --name smartretail-rg --location eastus

# Storage Account with hierarchical namespace (Data Lake Gen2)
az storage account create \
  --name smartretailstore \
  --resource-group smartretail-rg \
  --location eastus \
  --sku Standard_LRS \
  --enable-hierarchical-namespace true

# Create containers
az storage container create --account-name smartretailstore --name raw
az storage container create --account-name smartretailstore --name staging
az storage container create --account-name smartretailstore --name curated
az storage container create --account-name smartretailstore --name monitoring

# Azure Data Factory
az datafactory create \
  --resource-group smartretail-rg \
  --factory-name SmartRetail-ADF \
  --location eastus

# Azure Databricks Workspace
az databricks workspace create \
  --resource-group smartretail-rg \
  --name SmartRetail-DBW \
  --location eastus \
  --sku standard

# Azure Synapse Analytics (optional, for SQL DW integration)
az synapse workspace create \
  --name smartretail-synapse \
  --resource-group smartretail-rg \
  --storage-account smartretailstore \
  --file-system curated \
  --sql-admin-login-user sqladmin \
  --sql-admin-login-password <password>
```

### 2. Configure Environment Variables

Add to your `.env` file:

```env
# Azure Storage
AZURE_STORAGE_ACCOUNT=smartretailstore
AZURE_STORAGE_KEY=<storage-account-key>

# Azure Data Factory
AZURE_SUBSCRIPTION_ID=<subscription-id>
AZURE_RESOURCE_GROUP=smartretail-rg
ADF_FACTORY_NAME=SmartRetail-ADF

# Azure Databricks
DATABRICKS_WORKSPACE_URL=https://<workspace>.azuredatabricks.net
DATABRICKS_TOKEN=<personal-access-token>
DATABRICKS_CLUSTER_ID=<cluster-id>

# Service Principal (for ADF API access)
AZURE_TENANT_ID=<tenant-id>
AZURE_CLIENT_ID=<service-principal-client-id>
AZURE_CLIENT_SECRET=<service-principal-secret>
```

### 3. Deploy Data Factory Pipelines

#### Option A: Using Azure CLI

```bash
# Deploy master pipeline
az datafactory pipeline create \
  --resource-group smartretail-rg \
  --factory-name SmartRetail-ADF \
  --name SmartRetail_Master_Pipeline \
  --pipeline @infrastructure/azure/data_factory/pipeline_master.json

# Deploy ingestion pipeline
az datafactory pipeline create \
  --resource-group smartretail-rg \
  --factory-name SmartRetail-ADF \
  --name Ingest_Raw_Data_Pipeline \
  --pipeline @infrastructure/azure/data_factory/pipeline_ingest_raw.json

# Deploy transformation pipeline
az datafactory pipeline create \
  --resource-group smartretail-rg \
  --factory-name SmartRetail-ADF \
  --name Transform_Staged_Pipeline \
  --pipeline @infrastructure/azure/data_factory/pipeline_transform.json

# Deploy curation pipeline
az datafactory pipeline create \
  --resource-group smartretail-rg \
  --factory-name SmartRetail-ADF \
  --name Curate_Analytics_Pipeline \
  --pipeline @infrastructure/azure/data_factory/pipeline_curate.json
```

#### Option B: Using Azure Portal

1. Open Azure Data Factory Studio
2. Click "Author" → "Pipelines"
3. Import JSON for each pipeline
4. Configure linked services:
   - Azure Blob Storage (ADLS Gen2)
   - Azure Databricks
   - Azure SQL Database (for metadata)

### 4. Setup Databricks

#### Create Cluster

```python
# Cluster configuration
{
    "cluster_name": "SmartRetail-ETL",
    "spark_version": "13.3.x-scala2.12",
    "node_type_id": "Standard_DS3_v2",
    "num_workers": 2,
    "autotermination_minutes": 60,
    "spark_conf": {
        "spark.sql.adaptive.enabled": "true",
        "spark.sql.adaptive.coalescePartitions.enabled": "true",
        "spark.databricks.delta.optimizeWrite.enabled": "true",
        "spark.databricks.delta.autoCompact.enabled": "true"
    },
    "init_scripts": [
        {
            "dbfs": {
                "destination": "dbfs:/databricks/init-scripts/install-libraries.sh"
            }
        }
    ]
}
```

#### Install Libraries

```bash
# Create init script
cat > install-libraries.sh << 'EOF'
#!/bin/bash
pip install delta-spark==2.4.0
pip install great_expectations==0.17.0
EOF

# Upload to DBFS
databricks fs cp install-libraries.sh dbfs:/databricks/init-scripts/
```

#### Create Notebooks

1. Import notebooks from `infrastructure/azure/databricks/notebooks/`
2. Create folder structure: `/Shared/SmartRetail/`
3. Run `01_ingest_raw.py` to initialize tables
4. Execute SQL DDL from `delta_table_schemas.sql` in a notebook cell

### 5. Configure Microsoft Fabric (Optional)

1. Create workspace in Microsoft Fabric
2. Create Lakehouse "SmartRetail_Lakehouse"
3. Configure shortcuts to ADLS Gen2 containers:
   - raw → `abfss://raw@smartretailstore.dfs.core.windows.net`
   - staging → `abfss://staging@smartretailstore.dfs.core.windows.net`
   - curated → `abfss://curated@smartretailstore.dfs.core.windows.net`
4. Import lakehouse configuration from `lakehouse_config.json`

### 6. Create Dataflows for Power BI

In Microsoft Fabric:
1. Navigate to your Lakehouse
2. Create Dataflow Gen2
3. Add queries:
   - Sales summary: `SELECT * FROM curated.sales_daily`
   - Customer 360: `SELECT * FROM curated.customer_360`
   - Inventory: `SELECT * FROM curated.inventory_analytics`
4. Set refresh schedule (e.g., every 2 hours)
5. Connect to Power BI workspace

## Pipeline Execution

### Manual Trigger

```python
from app.services.data_pipeline_service import local_pipeline_service
from app.database import get_db

db = next(get_db())

# Run full pipeline
result = local_pipeline_service.run_full_pipeline(db)

print(f"Status: {result['status']}")
print(f"Processed: {result['layers']['curated']['total_records']} records")
print(f"Duration: {result['duration_seconds']:.2f}s")
```

### Scheduled Execution

#### Using Azure Data Factory Schedule Trigger

```json
{
  "name": "HourlyPipelineTrigger",
  "properties": {
    "type": "ScheduleTrigger",
    "typeProperties": {
      "recurrence": {
        "frequency": "Hour",
        "interval": 1,
        "startTime": "2024-01-01T00:00:00Z"
      }
    },
    "pipeline": {
      "pipelineReference": {
        "name": "SmartRetail_Master_Pipeline"
      }
    }
  }
}
```

#### Using Databricks Workflows

```python
# Create job to run all notebooks
job_config = {
    "name": "SmartRetail-Pipeline",
    "tasks": [
        {
            "task_key": "ingest",
            "notebook_task": {
                "notebook_path": "/Shared/SmartRetail/01_ingest_raw",
                "base_parameters": {
                    "output_path": "abfss://raw@smartretailstore.dfs.core.windows.net",
                    "execution_date": "{{jobs.trigger_time}}"
                }
            }
        },
        {
            "task_key": "transform",
            "depends_on": [{"task_key": "ingest"}],
            "notebook_task": {
                "notebook_path": "/Shared/SmartRetail/02_transform_staging"
            }
        },
        {
            "task_key": "curate",
            "depends_on": [{"task_key": "transform"}],
            "notebook_task": {
                "notebook_path": "/Shared/SmartRetail/03_curate_analytics"
            }
        },
        {
            "task_key": "quality",
            "depends_on": [{"task_key": "curate"}],
            "notebook_task": {
                "notebook_path": "/Shared/SmartRetail/04_data_quality_monitoring"
            }
        }
    ],
    "schedule": {
        "quartz_cron_expression": "0 0 * * * ?",
        "timezone_id": "UTC"
    }
}
```

## Data Quality Monitoring

### Quality Checks Implemented

| Check Type | Description | Threshold |
|------------|-------------|-----------|
| Completeness | Non-null percentage per column | ≥ 95% |
| Uniqueness | Duplicate detection | 0 duplicates |
| Range | Value within expected bounds | Per column |
| Referential Integrity | Foreign key validation | No orphans |
| Freshness | Data age | ≤ 24 hours |
| Statistical | Z-score outliers | |z| < 2.5 |

### Access Quality Reports

```python
# Get latest quality report
report = local_pipeline_service.get_data_quality_report(curated_data)

print(f"Quality Score: {report.quality_score:.1f}%")
print(f"Status: {report.status}")
print(f"Passed: {report.passed_checks}/{report.total_checks}")
```

### View in Databricks

```sql
-- Query quality log
SELECT 
    execution_date,
    table_name,
    check_name,
    passed,
    severity,
    details
FROM monitoring.data_quality_log
WHERE execution_date = current_date()
ORDER BY check_timestamp DESC;

-- Daily quality score trend
SELECT 
    execution_date,
    quality_score,
    status,
    total_checks,
    failed_checks
FROM monitoring.quality_score_daily
ORDER BY execution_date DESC
LIMIT 30;
```

## Delta Lake Features

### Time Travel

```python
# Query as of yesterday
yesterday_df = spark.read \
    .format("delta") \
    .option("timestampAsOf", "2024-01-01T00:00:00Z") \
    .load("abfss://curated@smartretailstore.dfs.core.windows.net/sales_daily")

# Query specific version
version_df = spark.read \
    .format("delta") \
    .option("versionAsOf", 5234) \
    .load("abfss://curated@smartretailstore.dfs.core.windows.net/customer_360")
```

### Optimize and Vacuum

```sql
-- Optimize table for faster queries
OPTIMIZE curated.sales_daily ZORDER BY (created_at);

-- Remove old versions (retain 7 days)
VACUUM curated.sales_daily RETAIN 168 HOURS;

-- Check table history
DESCRIBE HISTORY curated.customer_360;
```

### Schema Evolution

```sql
-- Add new column
ALTER TABLE curated.sales_daily ADD COLUMN promotion_flag BOOLEAN;

-- Update column comment
ALTER TABLE curated.customer_360 ALTER COLUMN churn_risk_score COMMENT 'ML predicted probability of churn';
```

## Integration with Application

### Python API Integration

```python
from app.services.data_pipeline_service import get_pipeline_data, export_pipeline_data_for_powerbi
from app.database import get_db

db = next(get_db())

# Get full pipeline data
pipeline_data = get_pipeline_data(db)

# Access specific layers
raw_orders = pipeline_data['data']['sales_daily']
customers = pipeline_data['data']['customer_360']

# Export for Power BI
powerbi_data = export_pipeline_data_for_powerbi(db)
```

### REST API Endpoints

See `app/routes/main.py` for:
- `/api/admin/pipeline/run` - Trigger pipeline
- `/api/admin/pipeline/status` - Get status
- `/api/admin/pipeline/data` - Get curated data
- `/api/admin/pipeline/quality` - Quality report

## Cost Optimization

### Auto-scaling

```python
# Enable auto-scaling on Databricks cluster
{
    "autoscale": {
        "min_workers": 1,
        "max_workers": 8
    }
}
```

### Storage Tiers

Configure lifecycle management:

```json
{
  "rules": [
    {
      "name": "raw-to-cool",
      "enabled": true,
      "type": "Lifecycle",
      "definition": {
        "filters": {
          "blobTypes": ["blockBlob"],
          "prefixMatch": ["raw/"]
        },
        "actions": {
          "baseBlob": {
            "tierToCool": { "daysAfterModificationGreaterThan": 30 }
          }
        }
      }
    }
  ]
}
```

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| Pipeline fails on authentication | Check service principal permissions |
| Delta table corruption | Run `REPAIR TABLE` or restore from time travel |
| Out of memory in Databricks | Increase cluster size or enable auto-scaling |
| Data quality failures | Check source data for schema changes |
| Slow queries | Run `OPTIMIZE` and `ZORDER` on frequently filtered columns |

### Monitoring Queries

```sql
-- Check pipeline runs
SELECT 
    pipeline_name,
    status,
    start_time,
    duration_minutes
FROM adf.pipeline_runs
WHERE start_time >= current_date() - 7
ORDER BY start_time DESC;

-- Check table sizes
SELECT 
    table_name,
    format_number(total_size_mb, 2) as size_mb,
    num_files,
    last_modified
FROM information_schema.tables
WHERE table_schema IN ('raw', 'staging', 'curated');
```

## Next Steps

1. Deploy to Azure using provided ARM templates
2. Configure CI/CD with Azure DevOps or GitHub Actions
3. Set up monitoring with Azure Monitor and Log Analytics
4. Enable Unity Catalog for governance
5. Implement data sharing with Delta Sharing
