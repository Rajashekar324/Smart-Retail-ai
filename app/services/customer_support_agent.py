from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

from app.models import CartItem, Order, Product, SupportTicket, User
from app.services.mongo_service import mongo_service
from app.services.rag_service import rag_service
from app.services.product_search_service import product_search_service
from app.utils import generate_ticket_number

BASE_DIR = Path(__file__).resolve().parents[2]
PDF_DIR = BASE_DIR / "data" / "product_pdfs"
PDF_DIR.mkdir(parents=True, exist_ok=True)


class ConversationMemory:
    """Manages conversation history for contextual responses"""
    
    def __init__(self, max_history: int = 10):
        self.max_history = max_history
        self.conversations: Dict[str, List[Dict[str, Any]]] = {}
    
    def add_message(self, user_id: str, role: str, content: str, metadata: Optional[Dict] = None):
        """Add a message to the conversation history"""
        if user_id not in self.conversations:
            self.conversations[user_id] = []
        
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
            "metadata": metadata or {}
        }
        
        self.conversations[user_id].append(message)
        
        # Keep only recent messages
        if len(self.conversations[user_id]) > self.max_history:
            self.conversations[user_id] = self.conversations[user_id][-self.max_history:]
    
    def get_history(self, user_id: str) -> List[Dict[str, Any]]:
        """Get conversation history for a user"""
        return self.conversations.get(user_id, [])
    
    def clear_history(self, user_id: str):
        """Clear conversation history for a user"""
        if user_id in self.conversations:
            del self.conversations[user_id]
    
    def get_context(self, user_id: str) -> str:
        """Get formatted context from conversation history"""
        history = self.get_history(user_id)
        if not history:
            return ""
        
        context_lines = []
        for msg in history[-5:]:  # Last 5 messages for context
            role = msg["role"].upper()
            content = msg["content"]
            context_lines.append(f"{role}: {content}")
        
        return "\n".join(context_lines)


class PDFProductSupport:
    """PDF-based product documentation support"""
    
    def __init__(self):
        self.pdf_cache = {}
    
    def index_pdf(self, pdf_path: Path):
        """Index a PDF file for product information"""
        try:
            import PyPDF2
            
            with open(pdf_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                text = ""
                for page in reader.pages:
                    text += page.extract_text()
            
            # Store in cache
            self.pdf_cache[pdf_path.stem] = {
                "text": text,
                "path": str(pdf_path),
                "indexed_at": datetime.utcnow().isoformat()
            }
            
            return True
        except Exception as e:
            print(f"Error indexing PDF {pdf_path}: {e}")
            return False
    
    def search_pdfs(self, query: str) -> List[Dict[str, Any]]:
        """Search indexed PDFs for product information"""
        results = []
        query_lower = query.lower()
        
        for filename, data in self.pdf_cache.items():
            text = data["text"].lower()
            if query_lower in text:
                # Find relevant snippet
                snippets = []
                lines = data["text"].split('\n')
                for i, line in enumerate(lines):
                    if query_lower in line.lower():
                        start = max(0, i - 2)
                        end = min(len(lines), i + 3)
                        snippet = '\n'.join(lines[start:end])
                        snippets.append(snippet)
                
                if snippets:
                    results.append({
                        "source": filename,
                        "snippets": snippets[:3],
                        "path": data["path"]
                    })
        
        return results
    
    def index_all_pdfs(self):
        """Index all PDFs in the PDF directory"""
        for pdf_file in PDF_DIR.glob("*.pdf"):
            self.index_pdf(pdf_file)


class CustomerSupportAgent:
    """Enhanced Customer Support Agent with AI capabilities"""
    
    def __init__(self):
        self.memory = ConversationMemory()
        self.pdf_support = PDFProductSupport()
        self.user_context = {}
        
        # Index PDFs on initialization
        self.pdf_support.index_all_pdfs()
    
    def get_sentiment(self, text: str) -> str:
        """Analyze sentiment of user message"""
        try:
            from app.services.azure_text_analytics import azure_text_analytics

            result = azure_text_analytics.analyze_sentiment(text)
            if result and result.sentiment in {"positive", "neutral", "negative"}:
                return result.sentiment
            if result and result.sentiment == "mixed":
                return "neutral"
        except Exception:
            pass

        positive_words = {"great", "good", "nice", "love", "awesome", "fast", "thanks", "perfect", "happy"}
        negative_words = {"late", "bad", "angry", "issue", "problem", "worst", "refund", "slow", "delay", "cancel", "damaged"}
        
        lowered = text.lower()
        score = sum(word in lowered for word in positive_words) - sum(word in lowered for word in negative_words)
        
        if score > 0:
            return "positive"
        if score < 0:
            return "negative"
        return "neutral"
    
    def _get_user_id(self, user_email: Optional[str]) -> str:
        """Get user identifier for memory"""
        return user_email or "guest"
    
    def _get_context(self, user_email: Optional[str]):
        """Get user context for personalization"""
        key = self._get_user_id(user_email)
        if key not in self.user_context:
            self.user_context[key] = {
                "last_products": [],
                "last_query": "",
                "last_category": None,
                "last_color": None,
                "last_price_limit": None,
                "pending_action": None,
                "order_tracking_count": 0,
                "return_inquiry_count": 0,
            }
        return self.user_context[key]
    
    def _get_personalized_greeting(self, user_email: Optional[str]) -> str:
        """Generate personalized greeting based on user history"""
        context = self._get_context(user_email)
        history = self.memory.get_history(self._get_user_id(user_email))
        
        if not history:
            return "Hi! I'm your AI Customer Support Assistant. I can help you with product recommendations, order tracking, returns, refunds, and any shopping questions. How can I assist you today?"
        
        if context["order_tracking_count"] > 2:
            return "Welcome back! I see you've been checking on your orders. Is there anything specific about your deliveries I can help you with?"
        
        if context["return_inquiry_count"] > 1:
            return "Hi again! Are you still looking into return options, or is there something else I can help you with?"
        
        return "Welcome back! I'm here to help with any questions about products, orders, or your account. What would you like to know?"
    
    def _search_knowledge_base(self, query: str) -> List[Dict]:
        """Search RAG knowledge base for FAQ and policy information"""
        try:
            return rag_service.search(query, n_results=3)
        except Exception:
            return []
    
    def _search_pdf_products(self, query: str) -> str:
        """Search PDF product documentation"""
        results = self.pdf_support.search_pdfs(query)
        if results:
            response = "I found some relevant information from our product documentation:\n\n"
            for result in results[:2]:
                response += f"From {result['source']}:\n"
                for snippet in result['snippets'][:2]:
                    response += f"- {snippet}\n"
                response += "\n"
            return response
        return ""
    
    def _get_ai_enhanced_response(self, query: str, context: str, user_email: Optional[str]) -> Optional[str]:
        """Get AI-enhanced response using Azure OpenAI (if configured)"""
        try:
            from app.config import settings
            
            if settings.llm_provider == "azure" and settings.openai_api_key:
                from openai import AzureOpenAI
                
                client = AzureOpenAI(
                    api_key=settings.openai_api_key,
                    api_version="2024-02-15-preview",
                    azure_endpoint=settings.azure_endpoint if hasattr(settings, 'azure_endpoint') else None
                )
                
                system_prompt = """You are a helpful customer support assistant for StyleHub AI Store. 
                You help customers with:
                - Product recommendations and information
                - Order tracking and status
                - Returns and refunds
                - General shopping assistance
                
                Be friendly, concise, and helpful. If you don't know something, suggest contacting human support."""
                
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Context:\n{context}\n\nUser Query: {query}"}
                ]
                
                response = client.chat.completions.create(
                    model="gpt-4",
                    messages=messages,
                    max_tokens=300,
                    temperature=0.7
                )
                
                return response.choices[0].message.content
        except Exception as e:
            print(f"AI enhancement error: {e}")
            return None
        
        return None
    
    def _enhanced_product_search(self, query: str, db: Session, user_email: Optional[str]) -> str:
        """AI-powered product search with semantic understanding"""
        try:
            # Use semantic search
            product_search_service.index_products(db)
            results = product_search_service.semantic_search(query, n_results=6, db=db)
            
            if results:
                response = "Here are some products that match what you're looking for:\n\n"
                for result in results[:4]:
                    response += f"• {result['name']} - ₹{result['price']:.0f} (Similarity: {result['similarity_score']:.2%})\n"
                return response
        except Exception as e:
            print(f"Semantic search error: {e}")
        
        # Fallback to basic search
        from app.services.chatbot import SupportChatbot
        basic_bot = SupportChatbot()
        context = self._get_context(user_email)
        products = basic_bot._find_products(query, db, context)
        return basic_bot._format_products(products)
    
    def _get_detailed_order_info(self, order: Order) -> str:
        """Get detailed order information with timeline"""
        timeline = {
            "Confirmed": "Your order has been confirmed and is being processed.",
            "Packed": "Your order has been packed and is ready for shipment.",
            "Shipped": "Your order has been shipped and is on its way.",
            "Out for Delivery": "Your order is out for delivery and will arrive soon.",
            "Delivered": "Your order has been delivered successfully.",
            "Cancelled": "Your order has been cancelled.",
            "Returned": "Your order has been returned."
        }
        
        status_message = timeline.get(order.status, f"Status: {order.status}")
        
        response = f"""Order Details:
• Order Number: {order.order_number}
• Tracking ID: {order.tracking_id}
• Status: {order.status}
• Status Update: {status_message}
• Total Amount: ₹{order.total_amount:.0f}
• Payment Method: {order.payment_method}
• Payment Status: {order.payment_status}
• Placed On: {order.created_at.strftime('%d %b %Y at %I:%M %p')}

Items:"""
        
        for item in order.items:
            response += f"\n• {item.product_name} (Qty: {item.quantity}) - ₹{item.unit_price * item.quantity:.0f}"
        
        if order.status in ["Shipped", "Out for Delivery"]:
            response += "\n\nYour order is on its way! You can track it using the tracking ID above."
        
        return response
    
    def _get_return_guidance(self, order: Optional[Order] = None) -> str:
        """Comprehensive return and refund guidance"""
        response = """Here's our return and refund policy:

📦 Return Policy:
• Returns accepted within 7 days of delivery
• Items must be unused with original tags
• Original packaging required
• Proof of purchase needed

🔄 Return Process:
1. Go to My Orders
2. Select the order to return
3. Click "Return" button
4. Select return reason
5. Submit return request

💰 Refund Process:
• Refunds initiated after return verification
• Online payments: 5-7 business days
• COD: Refund via bank transfer (7-10 days)
• You'll receive refund confirmation via email

❌ Non-returnable Items:
• Personalized items
• Innerwear
• Items damaged during use

Need help with a specific return? Share your order number and I'll guide you through it."""
        
        if order:
            response += f"\n\nFor order {order.order_number}:"
            if order.status == "Delivered":
                response += " You can request a return from My Orders section."
            elif order.return_status == "Return Requested":
                response += " Your return request is being processed."
            elif order.return_status == "Return Approved":
                response += " Your return has been approved. Ship the item back using the provided label."
            elif order.return_status == "Returned":
                response += " Your return has been completed."
            else:
                response += " Returns can only be requested after delivery."
        
        return response
    
    def answer(
        self,
        query: str,
        db: Session,
        user_email: Optional[str] = None,
        history=None,
        current_product_id=None,
    ):
        """Main answer method with enhanced AI capabilities"""
        user_id = self._get_user_id(user_email)
        context_data = self._get_context(user_email)
        sentiment = self.get_sentiment(query)
        
        # Store user message in memory
        self.memory.add_message(user_id, "user", query, {"sentiment": sentiment})
        
        # Get conversation context
        conversation_context = self.memory.get_context(user_id)
        
        q = query.lower().strip()
        response = None
        ticket_id = None
        
        # Try AI-enhanced response first
        if conversation_context:
            ai_response = self._get_ai_enhanced_response(query, conversation_context, user_email)
            if ai_response:
                response = ai_response
        
        # If AI didn't provide response, use rule-based logic
        if not response:
            # Import and use existing chatbot logic as base
            from app.services.chatbot import SupportChatbot
            basic_bot = SupportChatbot()
            
            # Handle greetings with personalization
            if any(word in q.split() for word in ["hello", "hi", "hey", "start"]):
                response = self._get_personalized_greeting(user_email)
            
            # Enhanced product search with AI
            elif any(word in q for word in ["show", "find", "search", "looking for", "recommend", "suggest"]):
                response = self._enhanced_product_search(query, db, user_email)
            
            # Raise ticket (check before order tracking to avoid conflict)
            elif any(phrase in q for phrase in ["raise ticket", "create ticket", "open ticket", "complaint", "support ticket"]):
                ticket = basic_bot.create_ticket(
                    db=db,
                    user_email=user_email,
                    subject="Customer support request",
                    issue=query,
                    sentiment=sentiment,
                    order_number=None,
                )
                ticket_id = ticket.ticket_number
                response = f"I've created a support ticket for you. Your ticket ID is {ticket.ticket_number}. Our team will look into this and get back to you soon."
            
            # Enhanced order tracking with detailed info
            elif "order" in q or "track" in q:
                order = basic_bot._find_order_from_query(query, db)
                if order:
                    response = self._get_detailed_order_info(order)
                    context_data["order_tracking_count"] += 1
                elif user_email:
                    orders = basic_bot._get_user_orders(db, user_email)
                    response = basic_bot._format_recent_orders(orders)
                else:
                    response = "I can help track your order. Please log in or share your Order ID/Tracking ID."
            
            # Enhanced return/refund guidance
            elif "return" in q or "refund" in q or "exchange" in q:
                order = basic_bot._find_order_from_query(query, db)
                response = self._get_return_guidance(order)
                context_data["return_inquiry_count"] += 1
            
            # Search knowledge base for FAQs
            elif any(word in q for word in ["policy", "how to", "what is", "faq", "help"]):
                kb_results = self._search_knowledge_base(query)
                if kb_results:
                    response = "Based on our knowledge base:\n\n"
                    for result in kb_results:
                        response += f"{result['text']}\n\n"
                else:
                    # Search PDFs
                    pdf_result = self._search_pdf_products(query)
                    if pdf_result:
                        response = pdf_result
                    else:
                        response = "I'd be happy to help with that. Could you provide more details so I can assist you better?"
            
            # Default to basic chatbot
            else:
                result = basic_bot.answer(query, db, user_email, history, current_product_id)
                response = result.get("response", "I'm here to help. Could you please rephrase your question?")
                ticket_id = result.get("ticket_id")
        
        # Store assistant response in memory
        self.memory.add_message(user_id, "assistant", response)
        
        # Log to MongoDB
        try:
            mongo_service.log_chat({
                "user_email": user_email or "guest",
                "message": query,
                "response": response,
                "sentiment": sentiment,
                "ticket_id": ticket_id,
                "context_used": bool(conversation_context),
                "ai_enhanced": response is not None
            })
        except Exception:
            pass
        
        # Build quick actions
        quick_actions = self._build_enhanced_quick_actions(query, user_email, context_data)
        
        return {
            "response": response,
            "sentiment": sentiment,
            "ticket_id": ticket_id,
            "quick_actions": quick_actions,
            "context_used": bool(conversation_context)
        }
    
    def _build_enhanced_quick_actions(self, query: str, user_email: Optional[str], context: dict) -> List[Dict]:
        """Build contextually relevant quick actions"""
        q = query.lower()
        actions = []
        
        def add(label: str, *, chat: Optional[str] = None, ticket: Optional[str] = None):
            payload = {"label": label}
            if chat:
                payload["chat"] = chat
            if ticket:
                payload["ticket"] = ticket
            if payload not in actions:
                actions.append(payload)
        
        # Context-aware actions
        if context["order_tracking_count"] > 0:
            add("Track Another Order", chat="Track my orders")
        
        if context["return_inquiry_count"] > 0:
            add("Return Policy Details", chat="What is the return policy?")
        
        # Query-specific actions
        if any(word in q for word in ["product", "find", "search", "recommend"]):
            add("Trending Products", chat="Show trending products")
            add("Personalized Picks", chat="Recommend products for me")
        
        if "order" in q or "track" in q:
            add("Order Status", chat="Track my orders")
            add("Cancel Order", chat="Cancel my order")
        
        if "return" in q or "refund" in q:
            add("Return Policy", chat="What is the return policy?")
            add("Refund Status", chat="Check my refund status")
        
        if user_email:
            add("My Orders", chat="Track my orders")
            add("My Cart", chat="Show my cart")
        
        add("Raise Ticket", ticket="Please raise a ticket - I need to speak with a human agent")
        
        return actions[:5]


customer_support_agent = CustomerSupportAgent()
