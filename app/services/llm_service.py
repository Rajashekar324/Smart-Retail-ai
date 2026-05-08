"""LLM Service for Multi-Agent System with OpenAI Integration"""
from __future__ import annotations

import os
import json
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
from functools import lru_cache

# Configure logging
logger = logging.getLogger(__name__)

# Try to import OpenAI
try:
    from openai import OpenAI, AzureOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("OpenAI not installed. Install with: pip install openai")

# Try to import LangChain components
try:
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
    from langchain.agents import AgentExecutor, create_openai_functions_agent
    from langchain.tools import Tool
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    logger.warning("LangChain not installed. Install with: pip install langchain-openai langchain")

# Try to import Chroma for vector store
try:
    from langchain_chroma import Chroma
    import chromadb
    CHROMA_AVAILABLE = True
except ImportError:
    try:
        from langchain_community.vectorstores import Chroma
        import chromadb
        CHROMA_AVAILABLE = True
    except ImportError:
        CHROMA_AVAILABLE = False
        logger.warning("ChromaDB not installed. Install with: pip install langchain-chroma chromadb")


class LLMConfig:
    """Configuration for LLM service"""
    
    def __init__(self):
        # Try to use app config if available, fallback to os.getenv
        try:
            from app.config import settings
            self.provider = settings.llm_provider or os.getenv("LLM_PROVIDER", "openai")
            self.openai_api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
            self.google_api_key = settings.google_api_key or os.getenv("GOOGLE_API_KEY")
            # Azure OpenAI settings
            self.azure_endpoint = settings.azure_openai_endpoint or os.getenv("AZURE_OPENAI_ENDPOINT")
            self.azure_api_key = settings.azure_openai_key or os.getenv("AZURE_OPENAI_KEY")
            self.azure_deployment = settings.azure_openai_deployment or os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4")
            self.azure_api_version = settings.azure_openai_api_version or os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
        except ImportError:
            self.provider = os.getenv("LLM_PROVIDER", "openai")
            self.openai_api_key = os.getenv("OPENAI_API_KEY")
            self.google_api_key = os.getenv("GOOGLE_API_KEY")
            # Azure OpenAI settings
            self.azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
            self.azure_api_key = os.getenv("AZURE_OPENAI_KEY")
            self.azure_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4")
            self.azure_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
        
        self.model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.7"))
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "2000"))
        
        # Validate configuration
        if self.provider == "openai" and not self.openai_api_key:
            logger.error("OpenAI API key not found. Please set OPENAI_API_KEY in .env file")
        elif self.provider == "azure" and (not self.azure_api_key or not self.azure_endpoint):
            logger.error("Azure OpenAI configuration incomplete. Please set AZURE_OPENAI_KEY and AZURE_OPENAI_ENDPOINT in .env file")


class VectorStore:
    """Vector store for RAG with ChromaDB"""
    
    def __init__(self, collection_name: str = "agent_knowledge"):
        self.collection_name = collection_name
        self.embeddings = None
        self.vectorstore = None
        self.config = LLMConfig()
        
        if CHROMA_AVAILABLE and LANGCHAIN_AVAILABLE:
            try:
                if self.config.provider == "azure":
                    self.embeddings = OpenAIEmbeddings(
                        api_key=self.config.azure_api_key,
                        base_url=self.config.azure_endpoint,
                        model=self.config.embedding_model,
                        api_version=self.config.azure_api_version,
                        deployment=self.config.azure_deployment
                    )
                else:
                    self.embeddings = OpenAIEmbeddings(
                        api_key=self.config.openai_api_key,
                        model=self.config.embedding_model
                    )
                
                # Initialize ChromaDB with persistence
                self.vectorstore = Chroma(
                    collection_name=collection_name,
                    embedding_function=self.embeddings,
                    persist_directory="./chroma_db"
                )
                logger.info(f"Vector store initialized: {collection_name}")
            except Exception as e:
                logger.error(f"Failed to initialize vector store: {e}")
    
    def add_documents(self, documents: List[str], metadatas: List[Dict] = None) -> bool:
        """Add documents to vector store"""
        if not self.vectorstore:
            logger.warning("Vector store not available")
            return False
        
        try:
            # Generate IDs
            ids = [f"doc_{i}_{datetime.now().timestamp()}" for i in range(len(documents))]
            
            self.vectorstore.add_texts(
                texts=documents,
                metadatas=metadatas or [{}] * len(documents),
                ids=ids
            )
            logger.info(f"Added {len(documents)} documents to vector store")
            return True
        except Exception as e:
            logger.error(f"Failed to add documents: {e}")
            return False
    
    def similarity_search(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """Search similar documents"""
        if not self.vectorstore:
            logger.warning("Vector store not available")
            return []
        
        try:
            results = self.vectorstore.similarity_search_with_score(query, k=k)
            return [
                {
                    "content": doc.page_content,
                    "metadata": doc.metadata,
                    "score": float(score)
                }
                for doc, score in results
            ]
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
    
    def get_relevant_context(self, query: str, k: int = 3) -> str:
        """Get relevant context as formatted string"""
        results = self.similarity_search(query, k=k)
        if not results:
            return ""
        
        context_parts = []
        for i, result in enumerate(results, 1):
            context_parts.append(f"[Document {i}]\n{result['content']}")
        
        return "\n\n".join(context_parts)


class LLMService:
    """Service for LLM interactions with OpenAI"""
    
    def __init__(self):
        self.config = LLMConfig()
        self.client = None
        self.llm = None
        self.vectorstore = VectorStore()
        
        # Initialize OpenAI client based on provider
        if OPENAI_AVAILABLE:
            try:
                if self.config.provider == "azure":
                    if self.config.azure_api_key and self.config.azure_endpoint:
                        self.client = AzureOpenAI(
                            api_key=self.config.azure_api_key,
                            azure_endpoint=self.config.azure_endpoint,
                            api_version=self.config.azure_api_version
                        )
                        logger.info("Azure OpenAI client initialized")
                    else:
                        logger.error("Azure OpenAI configuration incomplete")
                elif self.config.provider == "openai":
                    if self.config.openai_api_key:
                        self.client = OpenAI(api_key=self.config.openai_api_key)
                        logger.info("OpenAI client initialized")
                    else:
                        logger.error("OpenAI API key not found")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}")
        
        # Initialize LangChain LLM
        if LANGCHAIN_AVAILABLE:
            try:
                if self.config.provider == "azure":
                    if self.config.azure_api_key and self.config.azure_endpoint:
                        self.llm = ChatOpenAI(
                            api_key=self.config.azure_api_key,
                            base_url=self.config.azure_endpoint,
                            model=self.config.azure_deployment,
                            api_version=self.config.azure_api_version,
                            temperature=self.config.temperature,
                            max_tokens=self.config.max_tokens
                        )
                        logger.info("Azure LangChain LLM initialized")
                elif self.config.provider == "openai":
                    if self.config.openai_api_key:
                        self.llm = ChatOpenAI(
                            api_key=self.config.openai_api_key,
                            model=self.config.model,
                            temperature=self.config.temperature,
                            max_tokens=self.config.max_tokens
                        )
                        logger.info("OpenAI LangChain LLM initialized")
            except Exception as e:
                logger.error(f"Failed to initialize LangChain LLM: {e}")
    
    def is_available(self) -> bool:
        """Check if LLM service is available"""
        return self.client is not None or self.llm is not None
    
    def generate_response(
        self, 
        prompt: str, 
        system_prompt: str = None,
        context: str = None,
        temperature: float = None
    ) -> Dict[str, Any]:
        """Generate response using OpenAI"""
        
        if not self.is_available():
            return {
                "success": False,
                "error": "LLM service not available. Check API key configuration.",
                "response": None
            }
        
        try:
            # Build messages
            messages = []
            
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            
            # Add context if available (RAG)
            if context:
                context_prompt = f"Use the following context to answer:\n\n{context}\n\nQuestion: {prompt}"
                messages.append({"role": "user", "content": context_prompt})
            else:
                messages.append({"role": "user", "content": prompt})
            
            # Call OpenAI API
            model_name = self.config.azure_deployment if self.config.provider == "azure" else self.config.model
            response = self.client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature or self.config.temperature,
                max_tokens=self.config.max_tokens
            )
            
            return {
                "success": True,
                "response": response.choices[0].message.content,
                "model": model_name,
                "provider": self.config.provider,
                "tokens_used": response.usage.total_tokens if response.usage else None,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            error_str = str(e)
            logger.error(f"LLM generation failed: {error_str}")
            
            # Check for specific error types
            if "429" in error_str or "quota" in error_str.lower():
                provider_name = "Azure OpenAI" if self.config.provider == "azure" else "OpenAI"
                return {
                    "success": False,
                    "error": f"{provider_name} API quota exceeded. Please check your billing.",
                    "error_type": "quota_exceeded",
                    "response": None
                }
            elif "401" in error_str or "authentication" in error_str.lower():
                provider_name = "Azure OpenAI" if self.config.provider == "azure" else "OpenAI"
                return {
                    "success": False,
                    "error": f"Invalid {provider_name} API key. Please check your .env file.",
                    "error_type": "authentication",
                    "response": None
                }
            elif "timeout" in error_str.lower() or "connection" in error_str.lower():
                return {
                    "success": False,
                    "error": "Connection timeout. Please try again.",
                    "error_type": "timeout",
                    "response": None
                }
            else:
                return {
                    "success": False,
                    "error": error_str,
                    "response": None
                }
    
    def generate_with_rag(
        self,
        query: str,
        system_prompt: str = None,
        collection_name: str = None,
        k: int = 3
    ) -> Dict[str, Any]:
        """Generate response with RAG (Retrieval-Augmented Generation)"""
        
        # Retrieve relevant context
        context = self.vectorstore.get_relevant_context(query, k=k)
        
        # Generate response with context
        result = self.generate_response(query, system_prompt, context)
        
        # Add RAG metadata
        result["rag_used"] = bool(context)
        result["context_retrieved"] = context[:500] + "..." if len(context) > 500 else context
        
        return result
    
    def analyze_data_with_llm(
        self,
        data: Dict[str, Any],
        analysis_type: str,
        question: str = None
    ) -> Dict[str, Any]:
        """Analyze data using LLM with structured prompts"""
        
        # Build analysis prompt
        system_prompt = f"""You are an expert data analyst specializing in {analysis_type}.
Analyze the provided data and provide actionable insights in a structured format.
Be specific, quantitative, and provide recommendations."""
        
        data_json = json.dumps(data, indent=2, default=str)
        
        prompt = f"""Analyze the following {analysis_type} data:

```json
{data_json}
```

{question or 'Provide key insights, trends, anomalies, and actionable recommendations.'}

Format your response as:
1. **Key Insights** (3-5 bullet points)
2. **Trends & Patterns**
3. **Anomalies & Risks**
4. **Actionable Recommendations** (prioritized)
5. **Forecast/Prediction** (if applicable)"""
        
        return self.generate_response(prompt, system_prompt)
    
    def create_structured_output(
        self,
        prompt: str,
        output_schema: Dict[str, Any],
        system_prompt: str = None
    ) -> Dict[str, Any]:
        """Generate structured JSON output"""
        
        schema_desc = json.dumps(output_schema, indent=2)
        
        structured_system = system_prompt or "You are a helpful assistant that always responds in valid JSON format."
        structured_system += f"\n\nRespond ONLY with a valid JSON object matching this schema:\n{schema_desc}"
        
        result = self.generate_response(prompt, structured_system)
        
        if result["success"]:
            try:
                # Try to extract JSON from response
                response_text = result["response"]
                
                # Find JSON in markdown code blocks
                if "```json" in response_text:
                    json_str = response_text.split("```json")[1].split("```")[0].strip()
                elif "```" in response_text:
                    json_str = response_text.split("```")[1].split("```")[0].strip()
                else:
                    json_str = response_text.strip()
                
                parsed = json.loads(json_str)
                result["structured_output"] = parsed
            except Exception as e:
                logger.warning(f"Failed to parse structured output: {e}")
                result["structured_output"] = None
        
        return result


# Global LLM service instance
llm_service = LLMService()
vectorstore = VectorStore()
