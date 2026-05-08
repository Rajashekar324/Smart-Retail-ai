from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, Float
from sqlalchemy.ext.declarative import declarative_base
import json
import uuid
from pathlib import Path

Base = declarative_base()


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
                        limit: int = 10) -> List[Dict[str, Any]]:
        """Search documents using semantic search"""
        results = []
        
        # Try Azure Cognitive Search
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
                
                filter_query = f"document_type eq '{document_type}'" if document_type else None
                search_results = search_client.search(query, filter=filter_query, top=limit)
                
                for result in search_results:
                    results.append({
                        "document_id": result["id"],
                        "filename": result["filename"],
                        "document_type": result["document_type"],
                        "score": result["@search.score"],
                        "highlights": result.get("@search.highlights", {}),
                        "source": "azure_search"
                    })
                
                return results
        except:
            pass
        
        # Fallback to ChromaDB
        try:
            from app.services.document_search_service import user_document_search_service

            # Use get_or_create_collection to handle case when collection doesn't exist
            collection = user_document_search_service.chroma_client.get_or_create_collection("admin_documents")

            # Check if collection has any documents
            collection_count = collection.count()
            if collection_count == 0:
                print("ChromaDB admin_documents collection is empty, skipping semantic search")
            else:
                where_filter = {"document_type": document_type} if document_type else None

                chroma_results = collection.query(
                    query_texts=[query],
                    n_results=min(limit, collection_count),
                    where=where_filter
                )

                if chroma_results and chroma_results['ids'] and len(chroma_results['ids'][0]) > 0:
                    for i, doc_id in enumerate(chroma_results['ids'][0]):
                        results.append({
                            "document_id": doc_id,
                            "filename": chroma_results['metadatas'][0][i].get('filename', 'Unknown'),
                            "document_type": chroma_results['metadatas'][0][i].get('document_type', 'Unknown'),
                            "score": chroma_results['distances'][0][i] if 'distances' in chroma_results else None,
                            "source": "chromadb"
                        })
        except Exception as e:
            print(f"ChromaDB search error: {e}")
        
        # Fallback to database search (text search in filename and OCR text)
        if not results:
            from sqlalchemy import or_

            # Search in both filename and OCR text
            search_filter = or_(
                AdminDocument.original_filename.ilike(f'%{query}%'),
                AdminDocument.ocr_text.contains(query)
            )

            docs_query = db.query(AdminDocument).filter(search_filter)

            if document_type:
                docs_query = docs_query.filter(AdminDocument.document_type == document_type)

            docs = docs_query.limit(limit).all()

            for doc in docs:
                results.append({
                    "document_id": doc.document_id,
                    "filename": doc.original_filename,
                    "document_type": doc.document_type,
                    "status": doc.status,
                    "source": "database"
                })
        
        return results
    
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
