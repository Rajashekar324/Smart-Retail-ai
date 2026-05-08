from __future__ import annotations

from pathlib import Path
from typing import List, Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parents[2]
USER_DOCS_DIR = BASE_DIR / "data" / "user_documents"
CHROMA_USER_DOCS_DIR = BASE_DIR / "data" / "chroma_user_docs"

USER_DOCS_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_USER_DOCS_DIR.mkdir(parents=True, exist_ok=True)


class UserDocumentSearchService:
    """Document search service for user-side document queries"""
    
    def __init__(self):
        # ChromaDB disabled due to initialization errors
        self.client = None
        self.chroma_enabled = False
        self.embedding_model = None
        self.manuals_collection = None
        self.policies_collection = None
    
    def extract_text_from_pdf(self, pdf_path: Path) -> str:
        """Extract text from PDF file"""
        try:
            with open(pdf_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                text = ""
                for page in reader.pages:
                    text += page.extract_text() + "\n"
            return text
        except Exception as e:
            print(f"Error extracting text from {pdf_path}: {e}")
            return ""
    
    def chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
        """Split text into chunks for better search"""
        chunks = []
        words = text.split()
        current_chunk = []
        current_size = 0
        
        for word in words:
            current_chunk.append(word)
            current_size += len(word) + 1  # +1 for space
            
            if current_size >= chunk_size:
                chunks.append(" ".join(current_chunk))
                # Keep overlap
                overlap_words = current_chunk[-overlap:] if overlap > 0 else []
                current_chunk = overlap_words
                current_size = sum(len(w) + 1 for w in current_chunk)
        
        if current_chunk:
            chunks.append(" ".join(current_chunk))
        
        return chunks
    
    def index_document(
        self,
        doc_id: str,
        title: str,
        text: str,
        doc_type: str,
        metadata: Optional[Dict] = None
    ) -> bool:
        """Index a document in ChromaDB"""
        try:
            collection = self.manuals_collection if doc_type == "manual" else self.policies_collection
            
            # Chunk the text
            chunks = self.chunk_text(text)
            
            # Generate embeddings
            embeddings = self.embedding_model.encode(chunks).tolist()
            
            # Create IDs for chunks
            chunk_ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
            
            # Create metadata for each chunk
            chunk_metadata = []
            for i in range(len(chunks)):
                meta = {
                    "doc_id": doc_id,
                    "title": title,
                    "chunk_index": i,
                    "total_chunks": len(chunks)
                }
                if metadata:
                    meta.update(metadata)
                chunk_metadata.append(meta)
            
            # Check if document already exists and remove
            existing = collection.get(where={"doc_id": doc_id})
            if existing and existing.get("ids"):
                collection.delete(where={"doc_id": doc_id})
            
            # Add to collection
            collection.add(
                ids=chunk_ids,
                documents=chunks,
                metadatas=chunk_metadata,
                embeddings=embeddings
            )
            
            return True
        except Exception as e:
            print(f"Error indexing document {doc_id}: {e}")
            return False
    
    def search_manuals(self, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """Search product manuals"""
        try:
            query_embedding = self.embedding_model.encode([query]).tolist()
            
            results = self.manuals_collection.query(
                query_embeddings=query_embedding,
                n_results=n_results
            )
            
            documents = []
            if results.get("documents") and results["documents"][0]:
                for i, doc in enumerate(results["documents"][0]):
                    metadata = results["metadatas"][0][i]
                    distance = results["distances"][0][i]
                    documents.append({
                        "text": doc,
                        "title": metadata.get("title", "Unknown"),
                        "doc_id": metadata.get("doc_id"),
                        "chunk_index": metadata.get("chunk_index"),
                        "similarity": 1 - distance
                    })
            
            return documents
        except Exception as e:
            print(f"Error searching manuals: {e}")
            return []
    
    def search_policies(self, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """Search return/refund policies"""
        try:
            query_embedding = self.embedding_model.encode([query]).tolist()
            
            results = self.policies_collection.query(
                query_embeddings=query_embedding,
                n_results=n_results
            )
            
            documents = []
            if results.get("documents") and results["documents"][0]:
                for i, doc in enumerate(results["documents"][0]):
                    metadata = results["metadatas"][0][i]
                    distance = results["distances"][0][i]
                    documents.append({
                        "text": doc,
                        "title": metadata.get("title", "Unknown"),
                        "doc_id": metadata.get("doc_id"),
                        "chunk_index": metadata.get("chunk_index"),
                        "similarity": 1 - distance
                    })
            
            return documents
        except Exception as e:
            print(f"Error searching policies: {e}")
            return []
    
    def search_all_documents(self, query: str, n_results: int = 10) -> List[Dict[str, Any]]:
        """Search all document types"""
        manual_results = self.search_manuals(query, n_results=n_results // 2)
        policy_results = self.search_policies(query, n_results=n_results // 2)
        
        # Combine and sort by similarity
        all_results = manual_results + policy_results
        all_results.sort(key=lambda x: x["similarity"], reverse=True)
        
        return all_results[:n_results]
    
    def upload_and_index_pdf(
        self,
        pdf_path: Path,
        title: str,
        doc_type: str,
        metadata: Optional[Dict] = None
    ) -> bool:
        """Upload and index a PDF file"""
        if not pdf_path.exists():
            return False
        
        text = self.extract_text_from_pdf(pdf_path)
        if not text:
            return False
        
        doc_id = pdf_path.stem
        return self.index_document(doc_id, title, text, doc_type, metadata)
    
    def delete_document(self, doc_id: str, doc_type: str) -> bool:
        """Delete a document from the index"""
        try:
            collection = self.manuals_collection if doc_type == "manual" else self.policies_collection
            collection.delete(where={"doc_id": doc_id})
            return True
        except Exception as e:
            print(f"Error deleting document {doc_id}: {e}")
            return False
    
    def get_indexed_documents(self, doc_type: str) -> List[Dict[str, Any]]:
        """Get list of indexed documents"""
        try:
            collection = self.manuals_collection if doc_type == "manual" else self.policies_collection
            results = collection.get()
            
            if not results or not results.get("metadatas"):
                return []
            
            # Extract unique documents
            docs = {}
            for metadata in results["metadatas"]:
                doc_id = metadata.get("doc_id")
                if doc_id and doc_id not in docs:
                    docs[doc_id] = {
                        "doc_id": doc_id,
                        "title": metadata.get("title", "Unknown"),
                        "total_chunks": metadata.get("total_chunks", 0)
                    }
            
            return list(docs.values())
        except Exception as e:
            print(f"Error getting indexed documents: {e}")
            return []


user_document_search_service = UserDocumentSearchService()
