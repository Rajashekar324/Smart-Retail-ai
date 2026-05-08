"""
🔥 RAG PIPELINE - Internal Service
Handles document chunking, embeddings, vector indexing, and retrieval
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import hashlib
import re

# ChromaDB and sentence_transformers disabled due to initialization errors


@dataclass
class DocumentChunk:
    id: str
    text: str
    metadata: Dict[str, Any]
    embedding: Optional[List[float]] = None


class RAGPipelineService:
    """Internal RAG pipeline for document processing and retrieval"""
    
    def __init__(self):
        self.chunk_size = 512
        self.chunk_overlap = 50
        self.embedding_model = "text-embedding-ada-002"
        self.vector_store = None
        self.faiss_index = None
        self.azure_search = None
    
    def chunk_document(self, text: str, metadata: Dict[str, Any]) -> List[DocumentChunk]:
        """Split document into semantic chunks"""
        chunks = []
        
        # Clean and normalize text
        text = self._clean_text(text)
        
        # Split by sentences first
        sentences = re.split(r'(?<=[.!?])\s+', text)
        
        current_chunk = []
        current_length = 0
        chunk_index = 0
        
        for sentence in sentences:
            sentence_length = len(sentence.split())
            
            if current_length + sentence_length > self.chunk_size and current_chunk:
                # Save current chunk
                chunk_text = ' '.join(current_chunk)
                chunk_id = self._generate_chunk_id(chunk_text, metadata, chunk_index)
                
                chunks.append(DocumentChunk(
                    id=chunk_id,
                    text=chunk_text,
                    metadata={
                        **metadata,
                        'chunk_index': chunk_index,
                        'chunk_size': len(current_chunk),
                        'word_count': current_length
                    }
                ))
                
                # Overlap with previous chunk
                overlap_sentences = current_chunk[-self.chunk_overlap:] if len(current_chunk) > self.chunk_overlap else current_chunk
                current_chunk = overlap_sentences + [sentence]
                current_length = sum(len(s.split()) for s in current_chunk)
                chunk_index += 1
            else:
                current_chunk.append(sentence)
                current_length += sentence_length
        
        # Add remaining chunk
        if current_chunk:
            chunk_text = ' '.join(current_chunk)
            chunk_id = self._generate_chunk_id(chunk_text, metadata, chunk_index)
            chunks.append(DocumentChunk(
                id=chunk_id,
                text=chunk_text,
                metadata={
                    **metadata,
                    'chunk_index': chunk_index,
                    'chunk_size': len(current_chunk),
                    'word_count': current_length
                }
            ))
        
        return chunks
    
    def _clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        # Remove special characters but keep sentence structure
        text = re.sub(r'[^\w\s.!?-]', ' ', text)
        return text.strip()
    
    def _generate_chunk_id(self, text: str, metadata: Dict, index: int) -> str:
        """Generate unique chunk ID"""
        content = f"{metadata.get('source', 'unknown')}_{index}_{text[:100]}"
        return hashlib.md5(content.encode()).hexdigest()[:16]
    
    def generate_embeddings(self, chunks: List[DocumentChunk]) -> List[DocumentChunk]:
        """Generate embeddings for chunks"""
        try:
            # Try Azure OpenAI
            from openai import AzureOpenAI
            from app.config import settings
            
            client = AzureOpenAI(
                api_key=settings.azure_openai_key,
                api_version="2023-12-01-preview",
                azure_endpoint=settings.azure_openai_endpoint
            )
            
            texts = [chunk.text for chunk in chunks]
            response = client.embeddings.create(
                model=self.embedding_model,
                input=texts
            )
            
            for i, chunk in enumerate(chunks):
                chunk.embedding = response.data[i].embedding
            
            return chunks
            
        except Exception as e:
            print(f"Azure OpenAI embedding error: {e}")
            # Fallback to sentence-transformers
            try:
                from sentence_transformers import SentenceTransformer
                model = SentenceTransformer('all-MiniLM-L6-v2')
                
                texts = [chunk.text for chunk in chunks]
                embeddings = model.encode(texts)
                
                for i, chunk in enumerate(chunks):
                    chunk.embedding = embeddings[i].tolist()
                
                return chunks
            except Exception as e2:
                print(f"Sentence transformers error: {e2}")
                return chunks
    
    def index_chunks_chromadb(self, chunks: List[DocumentChunk], collection_name: str = "documents") -> bool:
        """Index chunks in ChromaDB"""
        try:
            import chromadb
            from chromadb.config import Settings
            
            client = chromadb.PersistentClient(
                path="./data/chromadb",
                settings=Settings(anonymized_telemetry=False)
            )
            
            collection = client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"}
            )
            
            # Only index chunks with embeddings
            chunks_with_embeddings = [c for c in chunks if c.embedding is not None]
            
            if chunks_with_embeddings:
                collection.add(
                    ids=[c.id for c in chunks_with_embeddings],
                    documents=[c.text for c in chunks_with_embeddings],
                    metadatas=[c.metadata for c in chunks_with_embeddings],
                    embeddings=[c.embedding for c in chunks_with_embeddings]
                )
            
            return True
        except Exception as e:
            print(f"ChromaDB indexing error: {e}")
            return False
    
    def index_chunks_faiss(self, chunks: List[DocumentChunk], index_path: str = "./data/faiss/index.faiss") -> bool:
        """Index chunks in FAISS"""
        try:
            import faiss
            
            chunks_with_embeddings = [c for c in chunks if c.embedding is not None]
            if not chunks_with_embeddings:
                return False
            
            dimension = len(chunks_with_embeddings[0].embedding)
            
            # Create or load index
            index = faiss.IndexFlatIP(dimension)  # Inner product for cosine similarity
            
            # Normalize embeddings
            embeddings = np.array([c.embedding for c in chunks_with_embeddings]).astype('float32')
            faiss.normalize_L2(embeddings)
            
            # Add to index
            index.add(embeddings)
            
            # Save index
            faiss.write_index(index, index_path)
            
            # Save metadata
            import json
            metadata = {c.id: {"text": c.text, "metadata": c.metadata} for c in chunks_with_embeddings}
            with open(index_path + ".meta", "w") as f:
                json.dump(metadata, f)
            
            return True
        except Exception as e:
            print(f"FAISS indexing error: {e}")
            return False
    
    def index_chunks_azure_search(self, chunks: List[DocumentChunk], index_name: str = "documents") -> bool:
        """Index chunks in Azure Cognitive Search"""
        try:
            from azure.search.documents import SearchClient
            from azure.core.credentials import AzureKeyCredential
            from app.config import settings
            
            search_client = SearchClient(
                endpoint=settings.azure_search_endpoint,
                index_name=index_name,
                credential=AzureKeyCredential(settings.azure_search_key)
            )
            
            documents = []
            for chunk in chunks:
                if chunk.embedding:
                    documents.append({
                        "id": chunk.id,
                        "content": chunk.text,
                        "embedding": chunk.embedding,
                        **chunk.metadata
                    })
            
            if documents:
                search_client.upload_documents(documents)
            
            return True
        except Exception as e:
            print(f"Azure Search indexing error: {e}")
            return False
    
    def retrieve_chromadb(self, query: str, collection_name: str = "documents", top_k: int = 5) -> List[Dict[str, Any]]:
        """Retrieve from ChromaDB"""
        try:
            import chromadb
            from chromadb.config import Settings
            
            client = chromadb.PersistentClient(
                path="./data/chromadb",
                settings=Settings(anonymized_telemetry=False)
            )
            
            collection = client.get_collection(name=collection_name)
            
            results = collection.query(
                query_texts=[query],
                n_results=top_k
            )
            
            retrieved = []
            for i in range(len(results['ids'][0])):
                retrieved.append({
                    'id': results['ids'][0][i],
                    'text': results['documents'][0][i],
                    'metadata': results['metadatas'][0][i],
                    'score': results['distances'][0][i] if 'distances' in results else None
                })
            
            return retrieved
        except Exception as e:
            print(f"ChromaDB retrieval error: {e}")
            return []
    
    def retrieve_faiss(self, query: str, index_path: str = "./data/faiss/index.faiss", top_k: int = 5) -> List[Dict[str, Any]]:
        """Retrieve from FAISS"""
        try:
            import faiss
            import json
            from sentence_transformers import SentenceTransformer
            
            # Load index
            index = faiss.read_index(index_path)
            
            # Load metadata
            with open(index_path + ".meta", "r") as f:
                metadata = json.load(f)
            
            # Generate query embedding
            model = SentenceTransformer('all-MiniLM-L6-v2')
            query_embedding = model.encode([query]).astype('float32')
            faiss.normalize_L2(query_embedding)
            
            # Search
            scores, indices = index.search(query_embedding, top_k)
            
            # Map back to documents
            ids = list(metadata.keys())
            retrieved = []
            for idx, score in zip(indices[0], scores[0]):
                if idx < len(ids):
                    doc_id = ids[idx]
                    retrieved.append({
                        'id': doc_id,
                        'text': metadata[doc_id]['text'],
                        'metadata': metadata[doc_id]['metadata'],
                        'score': float(score)
                    })
            
            return retrieved
        except Exception as e:
            print(f"FAISS retrieval error: {e}")
            return []
    
    def full_rag_pipeline(self, documents: List[Dict[str, Any]], query: str, 
                         vector_store: str = "chromadb") -> Dict[str, Any]:
        """Execute full RAG pipeline"""
        results = {
            'query': query,
            'vector_store': vector_store,
            'chunks_processed': 0,
            'chunks_indexed': 0,
            'retrieved_documents': [],
            'success': False
        }
        
        try:
            # Step 1: Chunk all documents
            all_chunks = []
            for doc in documents:
                chunks = self.chunk_document(doc['text'], doc.get('metadata', {}))
                all_chunks.extend(chunks)
            
            results['chunks_processed'] = len(all_chunks)
            
            # Step 2: Generate embeddings
            all_chunks = self.generate_embeddings(all_chunks)
            
            # Step 3: Index based on vector store choice
            if vector_store == "chromadb":
                success = self.index_chunks_chromadb(all_chunks)
            elif vector_store == "faiss":
                success = self.index_chunks_faiss(all_chunks)
            elif vector_store == "azure_search":
                success = self.index_chunks_azure_search(all_chunks)
            else:
                success = self.index_chunks_chromadb(all_chunks)
            
            if success:
                results['chunks_indexed'] = len([c for c in all_chunks if c.embedding])
            
            # Step 4: Retrieve
            if vector_store == "chromadb":
                retrieved = self.retrieve_chromadb(query)
            elif vector_store == "faiss":
                retrieved = self.retrieve_faiss(query)
            else:
                retrieved = self.retrieve_chromadb(query)
            
            results['retrieved_documents'] = retrieved
            results['success'] = True
            
        except Exception as e:
            results['error'] = str(e)
        
        return results


rag_pipeline_service = RAGPipelineService()
