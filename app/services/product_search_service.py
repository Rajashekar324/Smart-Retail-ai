from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any
from sqlalchemy.orm import Session

from app.models import Product, Order, OrderItem, CartItem, WishlistItem

BASE_DIR = Path(__file__).resolve().parents[2]
CHROMA_DIR = BASE_DIR / "data" / "chroma_products"


class ProductSearchService:
    def __init__(self):
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        # ChromaDB disabled due to initialization errors
        self.client = None
        self.collection = None
        self.chroma_enabled = False
        self.embedding_model = None
    
    def get_product_text(self, product: Product) -> str:
        """Create searchable text from product fields"""
        return f"{product.name} {product.category} {product.description}"
    
    def index_products(self, db: Session):
        """Index all products in ChromaDB"""
        # Skip if ChromaDB is disabled
        if not self.chroma_enabled or not self.collection or not self.embedding_model:
            return
            
        products = db.query(Product).all()
        
        if not products:
            return
        
        texts = [self.get_product_text(p) for p in products]
        ids = [str(p.id) for p in products]
        
        metadatas = []
        for p in products:
            metadatas.append({
                "id": p.id,
                "name": p.name,
                "category": p.category,
                "price": float(p.price),
                "stock": p.stock,
                "sku": p.sku
            })
        
        # Clear existing collection and re-index
        try:
            self.collection.delete()
        except:
            pass
        
        embeddings = self.embedding_model.encode(texts).tolist()
        
        self.collection.add(
            ids=ids,
            documents=texts,
            metadatas=metadatas,
            embeddings=embeddings
        )
    
    def semantic_search(self, query: str, n_results: int = 10, db: Session = None) -> List[Dict[str, Any]]:
        """AI-powered semantic product search"""
        # Fallback to simple text search since ChromaDB is disabled
        if not self.chroma_enabled or not self.collection or not db:
            if db:
                # Simple case-insensitive search on name and description
                search_term = f"%{query}%"
                return db.query(Product).filter(
                    (Product.name.ilike(search_term)) | 
                    (Product.description.ilike(search_term))
                ).limit(n_results).all()
            return []
        
        if self.collection.count() == 0:
            return []
        
        query_embedding = self.embedding_model.encode([query]).tolist()
        
        results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=n_results
        )
        
        products = []
        if results.get("ids") and results["ids"][0]:
            for i, product_id in enumerate(results["ids"][0]):
                metadata = results["metadatas"][0][i]
                distance = results["distances"][0][i]
                products.append({
                    "id": metadata["id"],
                    "name": metadata["name"],
                    "category": metadata["category"],
                    "price": metadata["price"],
                    "stock": metadata["stock"],
                    "sku": metadata["sku"],
                    "similarity_score": 1 - distance  # Convert distance to similarity
                })
        
        return products
    
    def get_similar_products(self, product_id: int, n_results: int = 6, db: Session = None) -> List[Product]:
        """Find similar products using vector similarity"""
        # Fallback to simple category matching since ChromaDB is disabled
        if not self.chroma_enabled or not self.collection or not db:
            if db:
                product = db.query(Product).filter(Product.id == product_id).first()
                if product and product.category:
                    return db.query(Product).filter(
                        Product.category == product.category,
                        Product.id != product_id
                    ).limit(n_results).all()
            return []
        
        if self.collection.count() == 0:
            return []
        
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            return []
        
        product_text = self.get_product_text(product)
        product_embedding = self.embedding_model.encode([product_text]).tolist()
        
        results = self.collection.query(
            query_embeddings=product_embedding,
            n_results=n_results + 1  # +1 to exclude the product itself
        )
        
        similar_ids = []
        if results.get("ids") and results["ids"][0]:
            for i, pid in enumerate(results["ids"][0]):
                if int(pid) != product_id:  # Exclude the product itself
                    similar_ids.append(int(pid))
        
        if similar_ids:
            return db.query(Product).filter(Product.id.in_(similar_ids[:n_results])).all()
        
        return []
    
    def get_personalized_recommendations(self, user_id: int, db: Session, limit: int = 8) -> List[Product]:
        """Get personalized recommendations based on user history"""
        # Get user's order history
        orders = db.query(Order).filter(Order.user_id == user_id).all()
        
        if not orders:
            # Fallback to trending products
            return db.query(Product).order_by(Product.stock.desc(), Product.created_at.desc()).limit(limit).all()
        
        # Get categories user has purchased
        purchased_categories = set()
        for order in orders:
            for item in order.items:
                product = db.query(Product).filter(Product.id == item.product_id).first()
                if product:
                    purchased_categories.add(product.category)
        
        # Get products from those categories (excluding already purchased)
        purchased_product_ids = set()
        for order in orders:
            for item in order.items:
                purchased_product_ids.add(item.product_id)
        
        if purchased_categories:
            recommendations = db.query(Product).filter(
                Product.category.in_(purchased_categories),
                Product.id.notin_(purchased_product_ids),
                Product.stock > 0
            ).order_by(Product.stock.desc(), Product.created_at.desc()).limit(limit).all()
            
            if recommendations:
                return recommendations
        
        # Fallback to trending
        return db.query(Product).order_by(Product.stock.desc(), Product.created_at.desc()).limit(limit).all()
    
    def get_frequently_bought_together(self, product_id: int, db: Session, limit: int = 4) -> List[Product]:
        """Find products frequently bought together with the given product"""
        # Find orders containing this product
        order_items = db.query(OrderItem).filter(OrderItem.product_id == product_id).all()
        order_ids = [oi.order_id for oi in order_items]
        
        if not order_ids:
            # Fallback to similar category products
            product = db.query(Product).filter(Product.id == product_id).first()
            if product:
                return db.query(Product).filter(
                    Product.category == product.category,
                    Product.id != product_id,
                    Product.stock > 0
                ).order_by(Product.stock.desc()).limit(limit).all()
            return []
        
        # Find other products in those orders
        other_order_items = db.query(OrderItem).filter(
            OrderItem.order_id.in_(order_ids),
            OrderItem.product_id != product_id
        ).all()
        
        # Count frequency
        product_freq = {}
        for oi in other_order_items:
            product_freq[oi.product_id] = product_freq.get(oi.product_id, 0) + 1
        
        # Sort by frequency and get top products
        sorted_products = sorted(product_freq.items(), key=lambda x: x[1], reverse=True)
        top_product_ids = [pid for pid, _ in sorted_products[:limit]]
        
        if top_product_ids:
            return db.query(Product).filter(Product.id.in_(top_product_ids)).all()
        
        # Fallback to similar category
        product = db.query(Product).filter(Product.id == product_id).first()
        if product:
            return db.query(Product).filter(
                Product.category == product.category,
                Product.id != product_id,
                Product.stock > 0
            ).order_by(Product.stock.desc()).limit(limit).all()
        
        return []
    
    def smart_filter(self, query: str, filters: Dict[str, Any], db: Session, n_results: int = 20) -> List[Dict[str, Any]]:
        """Smart filtering combining semantic search with metadata filters"""
        # First do semantic search
        semantic_results = self.semantic_search(query, n_results * 2, db)
        
        # Apply filters
        filtered_results = []
        for result in semantic_results:
            include = True
            
            if filters.get("category") and result["category"] != filters["category"]:
                include = False
            
            if filters.get("min_price") and result["price"] < filters["min_price"]:
                include = False
            
            if filters.get("max_price") and result["price"] > filters["max_price"]:
                include = False
            
            if filters.get("in_stock_only") and result["stock"] == 0:
                include = False
            
            if include:
                filtered_results.append(result)
        
        return filtered_results[:n_results]


product_search_service = ProductSearchService()
