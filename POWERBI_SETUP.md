# Power BI Analytics Integration Guide

## Overview

This guide explains how to set up and use the Power BI analytics dashboard integrated with Azure Power BI for the Smart Retail AI Store.

## Features

The Power BI integration provides:

- **📊 Sales Analytics**: Revenue trends, top products, order metrics
- **📈 Demand Forecasting**: AI-powered revenue and product demand predictions
- **🚨 Anomaly Detection**: Fraud detection and unusual pattern alerts
- **👥 Customer Insights**: Customer segmentation and behavior analysis
- **📦 Inventory Analytics**: Stock levels, turnover, and warehouse metrics
- **🤖 AI Agent Analytics**: Multi-agent system performance monitoring

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Power BI Dashboard                       │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │  Sales   │ │ Forecast │ │ Anomaly  │ │ Customer │       │
│  │ Analytics│ │   ing    │ │Detection │ │Insights  │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│  ┌──────────┐ ┌──────────┐                                   │
│  │ Inventory│ │  Agent   │                                   │
│  │Analytics │ │Analytics │                                   │
│  └──────────┘ └──────────┘                                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Data Export Layer                         │
│  - Sales Data        - Customer Data    - Inventory Data    │
│  - Support Tickets   - Daily Metrics    - Model Outputs     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  Smart Retail AI Store                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │  Orders  │ │ Products │ │  Users   │ │  Tickets │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                     │
│  │ Forecast │ │ Anomaly  │ │Segmenta-  │                     │
│  │ Service  │ │ Service  │ │tion Svc  │                     │
│  └──────────┘ └──────────┘ └──────────┘                     │
└─────────────────────────────────────────────────────────────┘
```

## Configuration

### 1. Environment Variables

Add the following to your `.env` file:

```env
# Azure AD Configuration (for Power BI API access)
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-service-principal-client-id
AZURE_CLIENT_SECRET=your-service-principal-secret

# Power BI Workspace Configuration
AZURE_POWERBI_WORKSPACE_ID=your-workspace-id
AZURE_POWERBI_REPORT_ID=your-report-id
AZURE_POWERBI_DATASET_ID=your-dataset-id

# Enable Power BI features
POWERBI_ENABLED=true
```

### 2. Azure Active Directory Setup

1. **Create Service Principal**:
   - Go to Azure Portal → Azure Active Directory → App registrations
   - Click "New registration"
   - Name: `SmartRetail-PowerBI`
   - Supported account types: Single tenant
   - Click "Register"

2. **Get Client Credentials**:
   - Copy "Application (client) ID" → `AZURE_CLIENT_ID`
   - Copy "Directory (tenant) ID" → `AZURE_TENANT_ID`
   - Go to "Certificates & secrets"
   - Create new client secret → `AZURE_CLIENT_SECRET`

3. **Add Power BI API Permissions**:
   - Go to "API permissions"
   - Add permission → Microsoft APIs → Power BI Service
   - Select:
     - `Dataset.Read.All`
     - `Report.Read.All`
     - `Workspace.Read.All`
   - Click "Grant admin consent"

### 3. Power BI Service Setup

1. **Create Workspace**:
   - Go to [Power BI Service](https://app.powerbi.com)
   - Click "Workspaces" → "Create a workspace"
   - Name: `Smart Retail Analytics`
   - Copy Workspace ID from URL → `AZURE_POWERBI_WORKSPACE_ID`

2. **Add Service Principal to Workspace**:
   - Open workspace settings
   - Go to "Access" tab
   - Add member by client ID
   - Role: Admin or Member

3. **Create Reports** (Optional):
   - Use the data export API (`/api/admin/powerbi/export`) to get JSON data
   - Import data into Power BI Desktop
   - Create visualizations
   - Publish to workspace
   - Copy Report ID → `AZURE_POWERBI_REPORT_ID`

## API Endpoints

### Dashboard APIs

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/powerbi` | GET | Power BI dashboard page |
| `/api/admin/powerbi/dashboards` | GET | List all dashboards |
| `/api/admin/powerbi/dashboards/{id}/visuals` | GET | Get dashboard visuals |

### Data Export APIs

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/admin/powerbi/export?dataset=all` | GET | Export all datasets |
| `/api/admin/powerbi/export?dataset=sales` | GET | Export sales data |
| `/api/admin/powerbi/export?dataset=customers` | GET | Export customer data |
| `/api/admin/powerbi/export?dataset=inventory` | GET | Export inventory data |
| `/api/admin/powerbi/export?dataset=tickets` | GET | Export tickets data |
| `/api/admin/powerbi/export?dataset=metrics` | GET | Export daily metrics |

### Analytics APIs

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/admin/powerbi/metrics` | GET | Get key metrics |
| `/api/admin/powerbi/model-outputs` | GET | Get AI model outputs |
| `/api/admin/powerbi/anomalies` | GET | Get anomaly alerts |
| `/api/admin/powerbi/insights` | GET | Get agent-driven insights |
| `/api/admin/powerbi/config` | GET | Get Power BI configuration |

## Data Export Format

### Sales Data
```json
{
  "sales_data": [
    {
      "order_id": 1,
      "order_number": "ORD-001",
      "order_date": "2024-01-15T10:30:00",
      "customer_id": 1,
      "customer_name": "John Doe",
      "product_id": 1,
      "product_name": "T-Shirt",
      "category": "Clothing",
      "quantity": 2,
      "unit_price": 499.99,
      "total_amount": 999.98,
      "status": "Delivered",
      "payment_method": "Online"
    }
  ]
}
```

### Customer Data
```json
{
  "customer_data": [
    {
      "customer_id": 1,
      "name": "John Doe",
      "email": "john@example.com",
      "registration_date": "2024-01-01T00:00:00",
      "total_orders": 5,
      "total_spent": 4999.99,
      "average_order_value": 999.99,
      "favorite_category": "Clothing"
    }
  ]
}
```

## Dashboards

### 1. Sales Analytics
- **Key Metrics**: Total revenue, orders, active users, AOV
- **Charts**: Revenue trends, orders vs revenue
- **Tables**: Top selling products
- **Insights**: Revenue summary and trends

### 2. Demand Forecasting
- **Key Metrics**: 30-day forecast, daily average, confidence, trend
- **Charts**: Revenue forecast with confidence intervals
- **Tables**: Weekly forecast summary
- **Insights**: Forecast summary and model information

### 3. Anomaly Detection
- **Key Metrics**: Total anomalies, high severity, order issues, inventory alerts
- **Charts**: Severity distribution (doughnut)
- **Tables**: Recent anomalies
- **Insights**: Alert summary and action items

### 4. Customer Insights
- **Key Metrics**: Total customers, VIP count, at-risk count, new customers
- **Charts**: Customer segments (doughnut)
- **Tables**: Segment summary
- **Insights**: Segmentation summary

### 5. Inventory Analytics
- **Key Metrics**: Total products, low stock items, out of stock, categories
- **Charts**: Inventory by category (bar)
- **Tables**: Low stock alerts
- **Insights**: Inventory status and alerts

### 6. AI Agent Analytics
- **Key Metrics**: Active agents, average health, tasks, orchestrator status
- **Charts**: Agent health scores (bar)
- **Tables**: Agent status
- **Insights**: Multi-agent system status

## Using Power BI Desktop

### 1. Connect to API Data Source

1. Open Power BI Desktop
2. Click "Get Data" → "Web"
3. Enter API URL: `http://your-server/api/admin/powerbi/export?dataset=all`
4. Add authentication header if needed
5. Transform JSON data using Power Query

### 2. Create Visualizations

Example DAX measures:
```dax
Total Revenue = SUM(sales_data[total_amount])

Total Orders = DISTINCTCOUNT(sales_data[order_id])

Average Order Value = DIVIDE([Total Revenue], [Total Orders])

Revenue Trend = 
    VAR CurrentMonth = [Total Revenue]
    VAR PreviousMonth = CALCULATE([Total Revenue], DATEADD('Date'[Date], -1, MONTH))
    RETURN DIVIDE(CurrentMonth - PreviousMonth, PreviousMonth)
```

### 3. Publish to Power BI Service

1. Click "Publish" in Power BI Desktop
2. Select your workspace
3. Configure refresh schedule (optional):
   - Go to dataset settings in Power BI Service
   - Set up scheduled refresh
   - Use API endpoint as data source

## Publishing and Sharing Reports

### 1. Power BI Service

1. **Publish Report**:
   - Upload .pbix file or publish from Desktop
   - Reports appear in workspace

2. **Create Dashboard**:
   - Pin visuals from reports to dashboard
   - Arrange tiles
   - Set refresh frequency

3. **Share**:
   - Click "Share" on dashboard
   - Add users/groups
   - Set permissions (View/Edit)

### 2. Embedded Analytics

For embedding in external applications:

```javascript
// Using Power BI JavaScript API
var embedConfig = {
    type: 'report',
    id: 'your-report-id',
    embedUrl: 'your-embed-url',
    accessToken: 'your-embed-token',
    settings: {
        filterPaneEnabled: true,
        navContentPaneEnabled: true
    }
};

var report = powerbi.embed(embedContainer, embedConfig);
```

### 3. Export Options

- **PDF**: Click Export → PDF from report
- **PowerPoint**: Export → PowerPoint
- **Excel**: Export underlying data
- **API**: Use Power BI REST API for programmatic export

## Troubleshooting

### Common Issues

1. **"Admin access required" error**:
   - Ensure user has `is_admin = True` in database

2. **Azure AD token errors**:
   - Verify AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET
   - Check service principal has Power BI API permissions
   - Ensure admin consent granted for permissions

3. **Empty dashboard data**:
   - Check database has orders/products/users
   - Verify API endpoints return data
   - Check browser console for JavaScript errors

4. **Report not embedding**:
   - Verify workspace ID and report ID
   - Check service principal has workspace access
   - Ensure Power BI Pro license for workspace

### Debug Commands

```bash
# Test Power BI configuration
curl http://localhost:8000/api/admin/powerbi/config

# Export data for verification
curl http://localhost:8000/api/admin/powerbi/export?dataset=metrics

# Check key metrics
curl http://localhost:8000/api/admin/powerbi/metrics
```

## Security Considerations

1. **Service Principal**: Use dedicated service principal for Power BI access
2. **Least Privilege**: Grant only required permissions
3. **Secret Rotation**: Regularly rotate client secrets
4. **Workspace Access**: Review workspace membership periodically
5. **Data Export**: Ensure sensitive data is properly filtered

## Next Steps

1. Configure Azure AD application
2. Set up Power BI workspace
3. Customize dashboards for your business needs
4. Set up scheduled data refresh
5. Share reports with stakeholders

## Support

For issues or questions:
- Check API logs in application
- Review Power BI activity logs in Azure
- Consult [Power BI REST API documentation](https://docs.microsoft.com/en-us/rest/api/power-bi/)
