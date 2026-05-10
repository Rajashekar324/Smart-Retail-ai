from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, Float
from sqlalchemy.ext.declarative import declarative_base
import json
import uuid
from pathlib import Path
import re

Base = declarative_base()

# Import LLM service for AI search
try:
    from app.services.llm_service import llm_service
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False


class AdminDocument(Base):
    __tablename__ = "admin_documents"
    
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(String(100), unique=True, nullable=False)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    document_type = Column(String(50), nullable=False)  # invoice, manual, policy, report
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String(100), nullable=True)
    
    # OCR and extraction results
    ocr_text = Column(Text, nullable=True)
    extracted_data = Column(Text, nullable=True)  # JSON
    
    # Azure Cognitive Search
    search_index_id = Column(String(100), nullable=True)
    embedding_id = Column(String(100), nullable=True)
    
    # Metadata
    uploaded_by = Column(Integer, nullable=False)
    status = Column(String(50), default="pending")  # pending, processing, indexed, error
    error_message = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DocumentIntelligencePanelService:
    """Document Intelligence Panel with Azure Document Intelligence and Cognitive Search"""
    
    def __init__(self):
        self.document_types = {
            "invoice": {"label": "Invoice", "prebuild_model": "prebuilt-invoice"},
            "manual": {"label": "Product Manual", "prebuild_model": "prebuilt-document"},
            "policy": {"label": "Policy Document", "prebuild_model": "prebuilt-document"},
            "report": {"label": "Report", "prebuild_model": "prebuilt-document"},
            "receipt": {"label": "Receipt", "prebuild_model": "prebuilt-receipt"},
            "id_document": {"label": "ID Document", "prebuild_model": "prebuilt-idDocument"}
        }
        self.upload_dir = Path("data/admin_documents")
        self.upload_dir.mkdir(parents=True, exist_ok=True)
    
    def store_document(self, db: Session, file_data: bytes, filename: str, 
                      document_type: str, uploaded_by: int, 
                      mime_type: str = None) -> Dict[str, Any]:
        """Store uploaded document"""
        # Generate unique ID
        doc_id = str(uuid.uuid4())
        
        # Create safe filename
        safe_filename = f"{doc_id}_{filename.replace(' ', '_')}"
        file_path = self.upload_dir / safe_filename
        
        # Save file
        with open(file_path, 'wb') as f:
            f.write(file_data)
        
        # Create database record
        doc = AdminDocument(
            document_id=doc_id,
            filename=safe_filename,
            original_filename=filename,
            document_type=document_type,
            file_path=str(file_path),
            file_size=len(file_data),
            mime_type=mime_type,
            uploaded_by=uploaded_by,
            status="pending"
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        
        return {
            "document_id": doc_id,
            "filename": filename,
            "document_type": document_type,
            "status": "pending",
            "message": "Document uploaded successfully. Processing will begin shortly."
        }
    
    def perform_ocr(self, db: Session, document_id: str) -> Dict[str, Any]:
        """Perform OCR using Azure Document Intelligence or fallback"""
        doc = db.query(AdminDocument).filter(AdminDocument.document_id == document_id).first()
        if not doc:
            return {"error": "Document not found"}
        
        try:
            # Try Azure Document Intelligence if available
            try:
                from azure.ai.formrecognizer import DocumentAnalysisClient
                from azure.core.credentials import AzureKeyCredential
                from app.config import settings
                
                if hasattr(settings, 'azure_document_intelligence_key') and settings.azure_document_intelligence_key:
                    client = DocumentAnalysisClient(
                        endpoint=settings.azure_document_intelligence_endpoint,
                        credential=AzureKeyCredential(settings.azure_document_intelligence_key)
                    )
                    
                    # Get prebuilt model for document type
                    model = self.document_types.get(doc.document_type, {}).get('prebuild_model', 'prebuilt-document')
                    
                    with open(doc.file_path, 'rb') as f:
                        poller = client.begin_analyze_document(model, f)
                        result = poller.result()
                    
                    # Extract text
                    full_text = ""
                    for page in result.pages:
                        for line in page.lines:
                            full_text += line.content + "\n"
                    
                    # Extract key-value pairs
                    extracted_data = {}
                    if result.key_value_pairs:
                        for kv in result.key_value_pairs:
                            if kv.key and kv.value:
                                extracted_data[kv.key.content] = kv.value.content
                    
                    # Extract tables
                    tables = []
                    for table in result.tables:
                        table_data = []
                        for cell in table.cells:
                            table_data.append({
                                "row": cell.row_index,
                                "col": cell.column_index,
                                "content": cell.content
                            })
                        tables.append(table_data)
                    
                    extracted_data['tables'] = tables
                    
                    doc.ocr_text = full_text
                    doc.extracted_data = json.dumps(extracted_data)
                    doc.status = "processed"
                    db.commit()
                    
                    return {
                        "document_id": document_id,
                        "status": "processed",
                        "text_length": len(full_text),
                        "extracted_fields": len(extracted_data) - (1 if 'tables' in extracted_data else 0),
                        "tables_found": len(tables),
                        "engine": "azure_document_intelligence"
                    }
            except ImportError:
                pass
            except Exception as e:
                print(f"Azure Document Intelligence error: {e}")
            
            # Fallback to PyPDF2 for PDFs or basic text extraction
            try:
                if doc.mime_type == 'application/pdf' or doc.filename.endswith('.pdf'):
                    try:
                        from PyPDF2 import PdfReader
                        reader = PdfReader(doc.file_path)
                        text = ""
                        for page in reader.pages:
                            text += page.extract_text() + "\n"
                        
                        doc.ocr_text = text
                        doc.extracted_data = json.dumps({"pages": len(reader.pages)})
                        doc.status = "processed"
                        db.commit()
                        
                        return {
                            "document_id": document_id,
                            "status": "processed",
                            "text_length": len(text),
                            "pages": len(reader.pages),
                            "engine": "pypdf2"
                        }
                    except ImportError:
                        pass
            except Exception as e:
                print(f"PDF extraction error: {e}")
            
            # Generic fallback
            doc.status = "error"
            doc.error_message = "OCR processing failed - unsupported format or processing error"
            db.commit()
            
            return {
                "document_id": document_id,
                "status": "error",
                "message": "OCR processing failed"
            }
            
        except Exception as e:
            doc.status = "error"
            doc.error_message = str(e)
            db.commit()
            return {"error": str(e)}
    
    def index_document(self, db: Session, document_id: str) -> Dict[str, Any]:
        """Index document in Azure Cognitive Search or ChromaDB"""
        doc = db.query(AdminDocument).filter(AdminDocument.document_id == document_id).first()
        if not doc or not doc.ocr_text:
            return {"error": "Document not found or not processed"}
        
        try:
            # Try Azure Cognitive Search if available
            try:
                from azure.search.documents import SearchClient
                from azure.core.credentials import AzureKeyCredential
                from app.config import settings
                
                if hasattr(settings, 'azure_search_key') and settings.azure_search_key:
                    search_client = SearchClient(
                        endpoint=settings.azure_search_endpoint,
                        index_name="admin-documents",
                        credential=AzureKeyCredential(settings.azure_search_key)
                    )
                    
                    search_doc = {
                        "id": doc.document_id,
                        "filename": doc.original_filename,
                        "document_type": doc.document_type,
                        "content": doc.ocr_text[:32000],  # Limit for search
                        "uploaded_by": doc.uploaded_by,
                        "created_at": doc.created_at.isoformat()
                    }
                    
                    search_client.upload_documents([search_doc])
                    doc.search_index_id = doc.document_id
                    doc.status = "indexed"
                    db.commit()
                    
                    return {
                        "document_id": document_id,
                        "status": "indexed",
                        "engine": "azure_cognitive_search"
                    }
            except ImportError:
                pass
            except Exception as e:
                print(f"Azure Search error: {e}")
            
            # Fallback to ChromaDB
            try:
                from app.services.document_search_service import user_document_search_service
                
                # Add to admin documents collection
                collection = user_document_search_service.chroma_client.get_or_create_collection("admin_documents")
                
                collection.add(
                    ids=[doc.document_id],
                    documents=[doc.ocr_text],
                    metadatas=[{
                        "filename": doc.original_filename,
                        "document_type": doc.document_type,
                        "uploaded_by": doc.uploaded_by
                    }]
                )
                
                doc.embedding_id = doc.document_id
                doc.status = "indexed"
                db.commit()
                
                return {
                    "document_id": document_id,
                    "status": "indexed",
                    "engine": "chromadb"
                }
            except Exception as e:
                print(f"ChromaDB indexing error: {e}")
            
            return {
                "document_id": document_id,
                "status": "processed",
                "message": "Document processed but not indexed"
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def search_documents(self, db: Session, query: str, document_type: str = None,
                        limit: int = 10, show_all_matches: bool = False) -> List[Dict[str, Any]]:
        """Azure AI Cognitive Search - finds all matching instances with highlighting
        
        Args:
            db: Database session
            query: Search query (phrase or word)
            document_type: Filter by document type
            limit: Maximum number of documents to return
            show_all_matches: If True, return all matches; if False, return first 5 matches per doc
        """
        results = []
        print(f"[DEBUG] search_documents called with query='{query}', doc_type='{document_type}', show_all={show_all_matches}")

        # Try Azure Cognitive Search first
        try:
            from azure.search.documents import SearchClient
            from azure.core.credentials import AzureKeyCredential
            from azure.search.documents.models import QueryType
            from app.config import settings

            print(f"[DEBUG] Azure key present: {bool(settings.azure_search_key)}, endpoint present: {bool(settings.azure_search_endpoint)}")

            if hasattr(settings, 'azure_search_key') and settings.azure_search_key:
                search_client = SearchClient(
                    endpoint=settings.azure_search_endpoint,
                    index_name="admin-documents",
                    credential=AzureKeyCredential(settings.azure_search_key)
                )

                # Build search query with highlighting - request more highlights for "Show All"
                search_results = search_client.search(
                    search_text=query,
                    query_type=QueryType.SIMPLE,
                    include_total_count=True,
                    top=limit,
                    highlight_fields="content",
                    highlight_pre_tag="<mark>",
                    highlight_post_tag="</mark>",
                    highlight_fragment_count=50 if show_all_matches else 20  # Get more fragments if showing all
                )

                for result in search_results:
                    # Get highlights (matching text with highlighting)
                    highlights = result.get('@search.highlights', {}).get('content', [])

                    # Build all_matches from highlights with proper yellow highlighting
                    all_matches = []
                    for idx, highlight in enumerate(highlights):
                        # Extract the plain text snippet (remove highlight tags for snippet)
                        snippet = highlight.replace('<mark>', '').replace('</mark>', '')
                        # Apply yellow highlighting style
                        highlighted_text = highlight.replace('<mark>', '<mark style="background: #ffeb3b; color: #000; padding: 2px 4px; border-radius: 3px; font-weight: bold;">')
                        all_matches.append({
                            "position": idx,
                            "snippet": snippet[:300],
                            "match_text": query,
                            "match_type": "azure_highlight",
                            "highlighted": highlighted_text
                        })

                    # Get first match for preview (with yellow highlighting)
                    first_match_highlighted = None
                    if highlights:
                        first_match_highlighted = highlights[0].replace('<mark>', '<mark style="background: #ffeb3b; color: #000; padding: 2px 4px; border-radius: 3px; font-weight: bold;">').replace('</mark>', '</mark>')

                    results.append({
                        "document_id": result.get("id"),
                        "filename": result.get("filename"),
                        "document_type": result.get("document_type"),
                        "status": "indexed",
                        "file_type": result.get("filename", "").split(".")[-1] if "." in result.get("filename", "") else "unknown",
                        "upload_date": result.get("created_at"),
                        "match_count": len(highlights),
                        "total_matches": len(highlights),  # Total count for "Show All"
                        "all_matches": all_matches if show_all_matches else all_matches[:5],  # Return first 5 or all
                        "initial_matches": all_matches[:5],  # Always include first 5
                        "content_snippet": first_match_highlighted,
                        "relevance_score": result.get("@search.score", 0),
                        "source": "azure_cognitive_search"
                    })

                # If Azure found results, add AI enhancement and return them
                if results:
                    # Add Text Analytics enhancement to each result
                    for result in results:
                        if result.get("all_matches"):
                            ai_enhancement = self.enhance_search_with_text_analytics(query, result["all_matches"])
                            result["ai_insights"] = ai_enhancement
                    return results[:limit]
                # If Azure returned no results (empty but no error), continue to local fallback
        except Exception as e:
            print(f"Azure Cognitive Search error: {e}")

        # Fallback: Local AI-powered search through database
        print(f"[DEBUG] Falling back to local search")
        local_results = self._local_search_documents(db, query, document_type, limit, show_all_matches)
        
        # Add AI enhancement to local results too
        for result in local_results:
            if result.get("all_matches"):
                ai_enhancement = self.enhance_search_with_text_analytics(query, result["all_matches"])
                result["ai_insights"] = ai_enhancement
        
        return local_results

    def _local_search_documents(self, db: Session, query: str, document_type: str = None,
                                limit: int = 10, show_all_matches: bool = False) -> List[Dict[str, Any]]:
        """Local search fallback when Azure is unavailable - supports word and phrase matching
        
        Args:
            db: Database session
            query: Search query
            document_type: Filter by document type
            limit: Maximum number of documents to return
            show_all_matches: If True, return all matches; if False, return first 5
        """
        results = []
        print(f"[DEBUG] _local_search_documents: query='{query}', doc_type='{document_type}', show_all={show_all_matches}")

        # Get all documents that have OCR text
        docs_query = db.query(AdminDocument).filter(
            AdminDocument.ocr_text.isnot(None),
            AdminDocument.status.in_(['processed', 'indexed'])
        )

        if document_type:
            docs_query = docs_query.filter(AdminDocument.document_type == document_type)

        docs = docs_query.all()
        print(f"[DEBUG] Found {len(docs)} documents with OCR text (status=processed/indexed)")

        # Build search patterns - support both phrase and word matching
        query_stripped = query.strip()
        is_phrase = ' ' in query_stripped  # Multi-word = phrase search
        print(f"[DEBUG] Searching for: '{query_stripped}', is_phrase={is_phrase}")

        for doc in docs:
            ocr_text = doc.ocr_text or ""
            if not ocr_text:
                continue

            text_lower = ocr_text.lower()
            query_lower = query_stripped.lower()

            all_matches = []

            if is_phrase:
                # Phrase search: look for exact phrase match (case-insensitive)
                start_pos = 0
                while True:
                    pos = text_lower.find(query_lower, start_pos)
                    if pos == -1:
                        break

                    context_start = max(0, pos - 150)
                    context_end = min(len(ocr_text), pos + len(query_stripped) + 150)
                    snippet = ocr_text[context_start:context_end].replace('\n', ' ')

                    # Create highlighted version with yellow background
                    highlighted = self._highlight_query(snippet, query_stripped)

                    all_matches.append({
                        "position": pos,
                        "snippet": snippet,
                        "match_text": ocr_text[pos:pos + len(query_stripped)],
                        "match_type": "phrase",
                        "highlighted": highlighted
                    })
                    start_pos = pos + len(query_stripped)
            else:
                # Word search: use word boundaries to match whole words only
                escaped_query = re.escape(query_lower)
                pattern = r'\b' + escaped_query + r'\b'

                for match in re.finditer(pattern, text_lower):
                    pos = match.start()
                    context_start = max(0, pos - 150)
                    context_end = min(len(ocr_text), pos + len(query_stripped) + 150)
                    snippet = ocr_text[context_start:context_end].replace('\n', ' ')

                    # Create highlighted version with yellow background
                    highlighted = self._highlight_query(snippet, query_stripped)

                    all_matches.append({
                        "position": pos,
                        "snippet": snippet,
                        "match_text": ocr_text[pos:pos + len(query_stripped)],
                        "match_type": "word",
                        "highlighted": highlighted
                    })

                # If no word matches found, try substring match as fallback
                if not all_matches:
                    start_pos = 0
                    while True:
                        pos = text_lower.find(query_lower, start_pos)
                        if pos == -1:
                            break

                        context_start = max(0, pos - 150)
                        context_end = min(len(ocr_text), pos + len(query_stripped) + 150)
                        snippet = ocr_text[context_start:context_end].replace('\n', ' ')

                        # Create highlighted version with yellow background
                        highlighted = self._highlight_query(snippet, query_stripped)

                        all_matches.append({
                            "position": pos,
                            "snippet": snippet,
                            "match_text": ocr_text[pos:pos + len(query_stripped)],
                            "match_type": "substring",
                            "highlighted": highlighted
                        })
                        start_pos = pos + len(query_stripped)

            if all_matches:
                file_ext = doc.filename.split('.')[-1] if '.' in doc.filename else 'unknown'

                # Generate highlighted snippet for preview
                first_match_highlighted = None
                if all_matches:
                    first_match_highlighted = self._highlight_query(all_matches[0]["snippet"], query_stripped)

                results.append({
                    "document_id": doc.document_id,
                    "filename": doc.original_filename,
                    "document_type": doc.document_type,
                    "status": doc.status,
                    "file_type": file_ext,
                    "upload_date": doc.created_at.isoformat() if doc.created_at else None,
                    "match_count": len(all_matches),
                    "total_matches": len(all_matches),
                    "all_matches": all_matches if show_all_matches else all_matches[:5],
                    "initial_matches": all_matches[:5],  # Always include first 5
                    "content_snippet": first_match_highlighted,
                    "relevance_score": len(all_matches),
                    "source": "local_search"
                })

        # Sort by match count (relevance)
        results.sort(key=lambda x: x.get("match_count", 0), reverse=True)
        print(f"[DEBUG] Local search returning {len(results)} results")
        return results[:limit]

    def _highlight_query(self, text: str, query: str) -> str:
        """Highlight query matches in text with yellow background"""
        if not text or not query:
            return text
        escaped_query = re.escape(query)
        regex = re.compile(f'({escaped_query})', re.IGNORECASE)
        return regex.sub(r'<mark style="background: #ffeb3b; color: #000; padding: 2px 4px; border-radius: 3px; font-weight: bold;">\1</mark>', text)

    def analyze_text_with_ai(self, text: str) -> Dict[str, Any]:
        """Analyze text using Azure Text Analytics for entities and key phrases
        
        Uses Azure AI Language service to extract:
        - Named entities (people, organizations, locations, etc.)
        - Key phrases
        - Sentiment (optional)
        
        Returns empty dict if Azure Text Analytics is not configured.
        """
        try:
            from azure.ai.textanalytics import TextAnalyticsClient
            from azure.core.credentials import AzureKeyCredential
            from app.config import settings

            # Check if Azure Text Analytics is configured
            if not hasattr(settings, 'azure_language_key') or not settings.azure_language_key:
                return {}

            if not hasattr(settings, 'azure_language_endpoint') or not settings.azure_language_endpoint:
                return {}

            # Initialize Text Analytics client
            text_analytics_client = TextAnalyticsClient(
                endpoint=settings.azure_language_endpoint,
                credential=AzureKeyCredential(settings.azure_language_key)
            )

            # Limit text length for API (max 5120 characters per document)
            text_to_analyze = text[:5000] if len(text) > 5000 else text

            documents = [{"id": "1", "text": text_to_analyze}]

            results = {
                "entities": [],
                "key_phrases": [],
                "azure_analyzed": True
            }

            # Extract entities
            try:
                entity_response = text_analytics_client.recognize_entities(documents)
                for doc_result in entity_response:
                    if not doc_result.is_error:
                        results["entities"] = [
                            {
                                "text": entity.text,
                                "category": entity.category,
                                "subcategory": entity.subcategory,
                                "confidence": entity.confidence_score
                            }
                            for entity in doc_result.entities
                        ]
            except Exception as e:
                print(f"Entity extraction error: {e}")

            # Extract key phrases
            try:
                key_phrase_response = text_analytics_client.extract_key_phrases(documents)
                for doc_result in key_phrase_response:
                    if not doc_result.is_error:
                        results["key_phrases"] = doc_result.key_phrases[:10]  # Top 10
            except Exception as e:
                print(f"Key phrase extraction error: {e}")

            return results

        except ImportError:
            print("Azure Text Analytics SDK not available")
            return {}
        except Exception as e:
            print(f"Azure Text Analytics error: {e}")
            return {}

    def enhance_search_with_text_analytics(self, query: str, matches: List[Dict]) -> Dict[str, Any]:
        """Enhance search results with Azure Text Analytics insights
        
        Analyzes the query and top matches to provide:
        - Query entities (what the user is looking for)
        - Related concepts from matching documents
        - Search context enhancement
        """
        enhancement = {
            "query_entities": [],
            "related_concepts": [],
            "search_suggestions": []
        }

        # Analyze the query itself
        query_analysis = self.analyze_text_with_ai(query)
        if query_analysis:
            enhancement["query_entities"] = query_analysis.get("entities", [])

        # Analyze top match snippets for related concepts
        all_snippets = " ".join([m.get("snippet", "") for m in matches[:3]])
        if all_snippets:
            snippet_analysis = self.analyze_text_with_ai(all_snippets)
            if snippet_analysis:
                enhancement["related_concepts"] = snippet_analysis.get("key_phrases", [])[:5]

        return enhancement

    def get_document(self, db: Session, document_id: str) -> Optional[Dict[str, Any]]:
        """Get document details"""
        doc = db.query(AdminDocument).filter(AdminDocument.document_id == document_id).first()
        if not doc:
            return None
        
        return {
            "document_id": doc.document_id,
            "filename": doc.original_filename,
            "document_type": doc.document_type,
            "file_size": doc.file_size,
            "mime_type": doc.mime_type,
            "status": doc.status,
            "ocr_text_preview": doc.ocr_text[:500] + "..." if doc.ocr_text and len(doc.ocr_text) > 500 else doc.ocr_text,
            "extracted_data": json.loads(doc.extracted_data) if doc.extracted_data else None,
            "uploaded_by": doc.uploaded_by,
            "created_at": doc.created_at.isoformat(),
            "error_message": doc.error_message
        }
    
    def list_documents(self, db: Session, document_type: str = None, 
                      status: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        """List all documents with filtering"""
        query = db.query(AdminDocument).order_by(AdminDocument.created_at.desc())
        
        if document_type:
            query = query.filter(AdminDocument.document_type == document_type)
        if status:
            query = query.filter(AdminDocument.status == status)
        
        docs = query.limit(limit).all()
        
        return [
            {
                "document_id": d.document_id,
                "filename": d.original_filename,
                "document_type": d.document_type,
                "file_size": d.file_size,
                "status": d.status,
                "uploaded_by": d.uploaded_by,
                "created_at": d.created_at.isoformat()
            }
            for d in docs
        ]
    
    def delete_document(self, db: Session, document_id: str) -> bool:
        """Delete a document"""
        doc = db.query(AdminDocument).filter(AdminDocument.document_id == document_id).first()
        if not doc:
            return False
        
        # Delete file
        try:
            Path(doc.file_path).unlink(missing_ok=True)
        except:
            pass
        
        # Delete from search index
        try:
            if doc.search_index_id:
                from azure.search.documents import SearchClient
                from azure.core.credentials import AzureKeyCredential
                from app.config import settings
                
                search_client = SearchClient(
                    endpoint=settings.azure_search_endpoint,
                    index_name="admin-documents",
                    credential=AzureKeyCredential(settings.azure_search_key)
                )
                search_client.delete_documents([{"id": document_id}])
        except:
            pass
        
        # Delete from ChromaDB
        try:
            if doc.embedding_id:
                from app.services.document_search_service import user_document_search_service
                collection = user_document_search_service.chroma_client.get_collection("admin_documents")
                collection.delete(ids=[document_id])
        except:
            pass
        
        # Delete from database
        db.delete(doc)
        db.commit()
        
        return True
    
    def get_document_types(self) -> Dict[str, str]:
        """Get available document types"""
        return {k: v["label"] for k, v in self.document_types.items()}


document_intelligence_service = DocumentIntelligencePanelService()
