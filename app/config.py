from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )
    
    app_name: str = "StyleHub AI Store"
    secret_key: str = ""  # Set in .env file
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7
    password_reset_expire_hours: int = 1
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "ai_support_store"
    admin_email: str = "admin@stylehub.com"
    admin_password: str = ""  # Set in .env file
    llm_provider: str = "offline"
    google_api_key: str = ""
    openai_api_key: str = ""
    
    # Azure OpenAI Settings
    azure_openai_endpoint: str = ""
    azure_openai_key: str = ""
    azure_openai_deployment: str = "gpt-4"
    azure_openai_api_version: str = "2024-02-15-preview"
    azure_endpoint: str = ""
    azure_storage_connection_string: str = ""
    azure_subscription_id: str = ""
    azure_resource_group: str = ""
    azure_ml_workspace: str = ""
    azure_keyvault_name: str = ""
    azure_document_intelligence_endpoint: str = ""
    azure_document_intelligence_key: str = ""
    azure_search_endpoint: str = ""
    azure_search_key: str = ""

    # Azure Power BI Settings
    azure_tenant_id: str = ""
    azure_client_id: str = ""
    azure_client_secret: str = ""
    azure_powerbi_workspace_id: str = ""
    azure_powerbi_report_id: str = ""
    azure_powerbi_dataset_id: str = ""
    powerbi_enabled: bool = False

    # Azure Data Pipeline Settings
    azure_storage_account: str = "smartretailstore"
    azure_storage_key: str = ""
    adf_factory_name: str = "SmartRetail-ADF"
    databricks_workspace_url: str = ""
    databricks_token: str = ""
    databricks_cluster_id: str = ""
    data_pipeline_enabled: bool = False
    data_pipeline_schedule: str = "0 */2 * * *"  # Every 2 hours

    # Azure AI Language (Text Analytics) Settings
    azure_language_key: str = ""
    azure_language_endpoint: str = ""
    azure_language_enabled: bool = False

    # MongoDB Settings for Reviews
    mongodb_reviews_uri: str = "mongodb://localhost:27017"
    mongodb_reviews_db: str = "smart_retail_reviews"

    # Email Settings
    mail_username: str = ""
    mail_password: str = ""
    mail_from: str = "no-reply@stylehub.local"
    mail_server: str = "localhost"
    mail_port: int = 587
    mail_tls: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
