"""
☁️ AZURE SERVICES - Internal Integration Service
Handles Azure OpenAI, Blob Storage, ML, Key Vault, AI Studio
"""
from __future__ import annotations

from typing import Dict, List, Any, Optional
from datetime import datetime
import json


class AzureIntegrationService:
    """Internal Azure cloud services integration"""
    
    def __init__(self):
        self.services = {
            'openai': None,
            'blob_storage': None,
            'ml': None,
            'key_vault': None,
            'ai_studio': None,
            'document_intelligence': None,
            'cognitive_search': None
        }
        self._init_connections()
    
    def _init_connections(self):
        """Initialize Azure service connections"""
        try:
            from app.config import settings
            
            # Azure OpenAI
            if hasattr(settings, 'azure_openai_key') and settings.azure_openai_key:
                from openai import AzureOpenAI
                self.services['openai'] = AzureOpenAI(
                    api_key=settings.azure_openai_key,
                    api_version="2023-12-01-preview",
                    azure_endpoint=settings.azure_openai_endpoint
                )
            
            # Azure Blob Storage
            if hasattr(settings, 'azure_storage_connection_string'):
                from azure.storage.blob import BlobServiceClient
                self.services['blob_storage'] = BlobServiceClient.from_connection_string(
                    settings.azure_storage_connection_string
                )
            
            # Azure ML
            if hasattr(settings, 'azure_ml_workspace'):
                from azure.ai.ml import MLClient
                from azure.identity import DefaultAzureCredential
                self.services['ml'] = MLClient(
                    credential=DefaultAzureCredential(),
                    subscription_id=settings.azure_subscription_id,
                    resource_group_name=settings.azure_resource_group,
                    workspace_name=settings.azure_ml_workspace
                )
            
            # Azure Key Vault
            if hasattr(settings, 'azure_keyvault_name'):
                from azure.keyvault.secrets import SecretClient
                from azure.identity import DefaultAzureCredential
                self.services['key_vault'] = SecretClient(
                    vault_url=f"https://{settings.azure_keyvault_name}.vault.azure.net/",
                    credential=DefaultAzureCredential()
                )
            
            # Azure Document Intelligence
            if hasattr(settings, 'azure_document_intelligence_key'):
                from azure.ai.formrecognizer import DocumentAnalysisClient
                from azure.core.credentials import AzureKeyCredential
                self.services['document_intelligence'] = DocumentAnalysisClient(
                    endpoint=settings.azure_document_intelligence_endpoint,
                    credential=AzureKeyCredential(settings.azure_document_intelligence_key)
                )
            
            # Azure Cognitive Search
            if hasattr(settings, 'azure_search_key'):
                from azure.search.documents import SearchClient
                from azure.core.credentials import AzureKeyCredential
                self.services['cognitive_search'] = SearchClient(
                    endpoint=settings.azure_search_endpoint,
                    index_name="documents",
                    credential=AzureKeyCredential(settings.azure_search_key)
                )
                
        except Exception as e:
            print(f"Azure initialization error: {e}")
    
    # Azure OpenAI Operations
    def openai_chat_completion(self, messages: List[Dict], model: str = "gpt-4", 
                              temperature: float = 0.7, max_tokens: int = 1000) -> Dict[str, Any]:
        """Internal Azure OpenAI chat completion"""
        try:
            client = self.services.get('openai')
            if not client:
                return {"error": "Azure OpenAI not configured"}
            
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            return {
                "content": response.choices[0].message.content,
                "model": response.model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                },
                "finish_reason": response.choices[0].finish_reason
            }
        except Exception as e:
            return {"error": str(e)}
    
    def openai_embeddings(self, texts: List[str], model: str = "text-embedding-ada-002") -> Dict[str, Any]:
        """Internal Azure OpenAI embeddings"""
        try:
            client = self.services.get('openai')
            if not client:
                return {"error": "Azure OpenAI not configured"}
            
            response = client.embeddings.create(
                model=model,
                input=texts
            )
            
            embeddings = [item.embedding for item in response.data]
            
            return {
                "embeddings": embeddings,
                "model": response.model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            }
        except Exception as e:
            return {"error": str(e)}
    
    # Azure Blob Storage Operations
    def blob_upload(self, container: str, blob_name: str, data: bytes, 
                   metadata: Dict = None) -> Dict[str, Any]:
        """Upload to Azure Blob Storage"""
        try:
            client = self.services.get('blob_storage')
            if not client:
                return {"error": "Azure Blob Storage not configured"}
            
            container_client = client.get_container_client(container)
            blob_client = container_client.get_blob_client(blob_name)
            
            blob_client.upload_blob(data, overwrite=True, metadata=metadata)
            
            return {
                "success": True,
                "container": container,
                "blob_name": blob_name,
                "url": blob_client.url
            }
        except Exception as e:
            return {"error": str(e)}
    
    def blob_download(self, container: str, blob_name: str) -> Dict[str, Any]:
        """Download from Azure Blob Storage"""
        try:
            client = self.services.get('blob_storage')
            if not client:
                return {"error": "Azure Blob Storage not configured"}
            
            container_client = client.get_container_client(container)
            blob_client = container_client.get_blob_client(blob_name)
            
            download_stream = blob_client.download_blob()
            data = download_stream.readall()
            
            return {
                "success": True,
                "data": data,
                "container": container,
                "blob_name": blob_name
            }
        except Exception as e:
            return {"error": str(e)}
    
    def blob_list(self, container: str, prefix: str = None) -> Dict[str, Any]:
        """List blobs in container"""
        try:
            client = self.services.get('blob_storage')
            if not client:
                return {"error": "Azure Blob Storage not configured"}
            
            container_client = client.get_container_client(container)
            blobs = list(container_client.list_blobs(name_starts_with=prefix))
            
            return {
                "success": True,
                "container": container,
                "blobs": [
                    {
                        "name": b.name,
                        "size": b.size,
                        "created": b.creation_time.isoformat() if b.creation_time else None,
                        "modified": b.last_modified.isoformat() if b.last_modified else None
                    }
                    for b in blobs
                ]
            }
        except Exception as e:
            return {"error": str(e)}
    
    # Azure ML Operations
    def ml_deploy_model(self, model_name: str, endpoint_name: str) -> Dict[str, Any]:
        """Deploy model to Azure ML endpoint"""
        try:
            client = self.services.get('ml')
            if not client:
                return {"error": "Azure ML not configured"}
            
            # Get model
            model = client.models.get(name=model_name, label="latest")
            
            # Create or update endpoint
            from azure.ai.ml.entities import ManagedOnlineEndpoint, ManagedOnlineDeployment
            
            endpoint = ManagedOnlineEndpoint(
                name=endpoint_name,
                description=f"Endpoint for {model_name}",
                auth_mode="key"
            )
            
            client.online_endpoints.begin_create_or_update(endpoint).result()
            
            deployment = ManagedOnlineDeployment(
                name="default",
                endpoint_name=endpoint_name,
                model=model,
                instance_type="Standard_DS3_v2",
                instance_count=1
            )
            
            client.online_deployments.begin_create_or_update(deployment).result()
            
            return {
                "success": True,
                "endpoint_name": endpoint_name,
                "model_name": model_name,
                "scoring_uri": client.online_endpoints.get(endpoint_name).scoring_uri
            }
        except Exception as e:
            return {"error": str(e)}
    
    def ml_invoke_endpoint(self, endpoint_name: str, data: Dict) -> Dict[str, Any]:
        """Invoke Azure ML endpoint"""
        try:
            client = self.services.get('ml')
            if not client:
                return {"error": "Azure ML not configured"}
            
            response = client.online_endpoints.invoke(
                endpoint_name=endpoint_name,
                request=json.dumps(data)
            )
            
            return {
                "success": True,
                "response": json.loads(response)
            }
        except Exception as e:
            return {"error": str(e)}
    
    # Azure Key Vault Operations
    def keyvault_get_secret(self, secret_name: str) -> Dict[str, Any]:
        """Get secret from Azure Key Vault"""
        try:
            client = self.services.get('key_vault')
            if not client:
                return {"error": "Azure Key Vault not configured"}
            
            secret = client.get_secret(secret_name)
            
            return {
                "success": True,
                "name": secret.name,
                "value": secret.value,
                "enabled": secret.properties.enabled
            }
        except Exception as e:
            return {"error": str(e)}
    
    def keyvault_set_secret(self, secret_name: str, value: str) -> Dict[str, Any]:
        """Set secret in Azure Key Vault"""
        try:
            client = self.services.get('key_vault')
            if not client:
                return {"error": "Azure Key Vault not configured"}
            
            secret = client.set_secret(secret_name, value)
            
            return {
                "success": True,
                "name": secret.name,
                "created": secret.properties.created_on.isoformat()
            }
        except Exception as e:
            return {"error": str(e)}
    
    # Azure Document Intelligence
    def analyze_document(self, document_path: str, model: str = "prebuilt-document") -> Dict[str, Any]:
        """Analyze document with Azure Document Intelligence"""
        try:
            client = self.services.get('document_intelligence')
            if not client:
                return {"error": "Azure Document Intelligence not configured"}
            
            with open(document_path, 'rb') as f:
                poller = client.begin_analyze_document(model, f)
                result = poller.result()
            
            # Extract content
            content = ""
            for page in result.pages:
                for line in page.lines:
                    content += line.content + "\n"
            
            # Extract key-value pairs
            key_values = {}
            if result.key_value_pairs:
                for kv in result.key_value_pairs:
                    if kv.key and kv.value:
                        key_values[kv.key.content] = kv.value.content
            
            return {
                "success": True,
                "content": content,
                "key_values": key_values,
                "pages": len(result.pages),
                "tables": len(result.tables) if result.tables else 0
            }
        except Exception as e:
            return {"error": str(e)}
    
    # Azure Cognitive Search
    def search_documents(self, query: str, top: int = 10) -> Dict[str, Any]:
        """Search documents with Azure Cognitive Search"""
        try:
            client = self.services.get('cognitive_search')
            if not client:
                return {"error": "Azure Cognitive Search not configured"}
            
            results = client.search(query, top=top)
            
            documents = []
            for result in results:
                documents.append({
                    "id": result["id"],
                    "content": result.get("content", ""),
                    "score": result["@search.score"],
                    "highlights": result.get("@search.highlights", {})
                })
            
            return {
                "success": True,
                "query": query,
                "count": len(documents),
                "documents": documents
            }
        except Exception as e:
            return {"error": str(e)}
    
    def get_service_status(self) -> Dict[str, Any]:
        """Get status of all Azure services"""
        status = {}
        for service_name, client in self.services.items():
            status[service_name] = {
                "configured": client is not None,
                "status": "ready" if client else "not_configured"
            }
        
        return {
            "services": status,
            "total": len(status),
            "configured": len([s for s in status.values() if s["configured"]]),
            "timestamp": datetime.utcnow().isoformat()
        }


azure_integration_service = AzureIntegrationService()
