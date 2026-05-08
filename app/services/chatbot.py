from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import CartItem, Order, Product, SupportTicket, User
from app.services.azure_text_analytics import azure_text_analytics
from app.services.mongo_service import mongo_service
from app.utils import generate_ticket_number


POSITIVE_WORDS = {
    "great", "good", "nice", "love", "awesome", "fast", "thanks", "perfect", "happy"
}
NEGATIVE_WORDS = {
    "late", "bad", "angry", "issue", "problem", "worst", "refund", "slow",
    "delay", "cancel", "damaged"
}


class SupportChatbot:
    def __init__(self):
        self.user_context = {}

    def get_sentiment(self, text: str) -> str:
        try:
            result = azure_text_analytics.analyze_sentiment(text)
            if result and x.sentiment in {"positive", "neutral", "negative"}:
                return result.sentiment
            if result and result.sentiment == "mixed":
                return "neutral"
        except Exception:
            pass

        lowered = text.lower()
        score = sum(word in lowered for word in POSITIVE_WORDS) - sum(
            word in lowered for word in NEGATIVE_WORDS
        )
        if score > 0:
            return "positive"
        if score < 0:
            return "negative"
        return "neutral"

    def _get_context(self, user_email: Optional[str]):
        key = user_email or "guest"
        if key not in self.user_context:
            self.user_context[key] = {
                "last_products": [],
                "last_query": "",
                "last_category": None,
                "last_color": None,
                "last_price_limit": None,
                "history": [],
                "pending_action": None,
            }
        return self.user_context[key]

    def _extract_price_limit(self, query: str):
        words = query.lower().replace("₹", "").replace(",", "").split()

        for i, word in enumerate(words):
            if word in {"under", "below", "less"} and i + 1 < len(words):
                try:
                    return float(words[i + 1])
                except Exception:
                    pass

        for word in words:
            cleaned = "".join(ch for ch in word if ch.isdigit())
            if cleaned.isdigit():
                return float(cleaned)

        return None

    def _extract_color(self, q: str):
        colors = [
            "black", "white", "blue", "red", "green", "pink",
            "grey", "gray", "brown", "yellow", "navy", "beige"
        ]
        return next((c for c in colors if c in q), None)

    def _extract_category(self, q: str):
        categories = [
            "shirt", "shirts", "jeans", "jacket", "jackets", "dress", "dresses",
            "shoes", "sneakers", "hoodie", "hoodies", "kurta", "kurtas",
            "tshirt", "t-shirts", "t-shirt", "top", "tops", "watch", "watches"
        ]
        return next((c for c in categories if c in q), None)

    def _find_products(self, query: str, db: Session, context: dict):
        q = query.lower()

        color = self._extract_color(q)
        category = self._extract_category(q)
        price_limit = self._extract_price_limit(query)

        if not color:
            color = context.get("last_color")
        if not category:
            category = context.get("last_category")
        if not price_limit:
            price_limit = context.get("last_price_limit")

        products = db.query(Product).all()
        matches = []

        for product in products:
            hay = f"{product.name} {product.category} {product.description}".lower()
            ok = True

            if color and color not in hay:
                ok = False

            if category:
                normalized_category = category.rstrip("s")
                if normalized_category not in hay:
                    ok = False

            if price_limit and product.price > price_limit:
                ok = False

            if ok:
                score = 0
                for token in q.split():
                    if token in hay:
                        score += 2
                if category and category.rstrip("s") in hay:
                    score += 4
                if color and color in hay:
                    score += 4
                if "men" in q and "men" in hay:
                    score += 3
                if "women" in q and "women" in hay:
                    score += 3
                matches.append((score, product))

        matches.sort(key=lambda x: (-x[0], x[1].price))
        result = [product for _, product in matches[:6]]

        context["last_products"] = result
        context["last_query"] = query
        context["last_category"] = category
        context["last_color"] = color
        context["last_price_limit"] = price_limit

        return result

    def _recommend_products(self, db: Session, context: dict, current_product_id=None):
        if current_product_id:
            current_product = db.query(Product).filter(Product.id == current_product_id).first()
            if current_product:
                recs = (
                    db.query(Product)
                    .filter(
                        Product.category == current_product.category,
                        Product.id != current_product.id,
                    )
                    .order_by(Product.stock.desc(), Product.created_at.desc())
                    .limit(4)
                    .all()
                )
                if recs:
                    return recs

        last_products = context.get("last_products", [])
        if last_products:
            base = last_products[0]
            recs = (
                db.query(Product)
                .filter(
                    Product.category == base.category,
                    Product.id != base.id,
                )
                .order_by(Product.stock.desc(), Product.created_at.desc())
                .limit(4)
                .all()
            )
            if recs:
                return recs

        return (
            db.query(Product)
            .order_by(Product.stock.desc(), Product.created_at.desc())
            .limit(4)
            .all()
        )


    def _build_quick_actions(self, query: str, user_email: Optional[str], context: dict, products=None):
        q = (query or '').lower()
        actions = []

        def add(label: str, *, chat: Optional[str] = None, ticket: Optional[str] = None):
            payload = {"label": label}
            if chat:
                payload["chat"] = chat
            if ticket:
                payload["ticket"] = ticket
            if payload not in actions:
                actions.append(payload)

        if any(word in q for word in ["recommend", "suggest", "similar", "find", "search", "shirt", "jeans", "dress", "jacket", "top", "hoodie", "shoes", "black", "blue", "women", "men"]):
            category = context.get("last_category")
            color = context.get("last_color")
            price_limit = context.get("last_price_limit")
            if color and category:
                add(f"More {color} {category}s", chat=f"Recommend {color} {category}s")
            if category:
                add(f"Best {category}s", chat=f"Recommend {category}s")
            if price_limit and category:
                add(f"Under ₹{int(price_limit)}", chat=f"Show {category}s under {int(price_limit)}")
            add("Track orders", chat="Track my orders")
            add("Track tickets", chat="Track my tickets")
        elif "ticket" in q:
            add("Track tickets", chat="Track my tickets")
            add("Raise ticket", ticket="Please raise a ticket - I need help with my recent order")
            add("Track orders", chat="Track my orders")
            add("My cart", chat="Show my cart")
        elif "cancel" in q:
            add("Track orders", chat="Track my orders")
            add("Cancel order", chat="Cancel my order")
            add("Track tickets", chat="Track my tickets")
            add("My cart", chat="Show my cart")
        elif "order" in q or "track" in q or "delivery" in q:
            add("Track orders", chat="Track my orders")
            add("Cancel order", chat="Cancel my order")
            add("Track tickets", chat="Track my tickets")
            add("My cart", chat="Show my cart")
        else:
            if user_email:
                add("Track orders", chat="Track my orders")
                add("Cancel order", chat="Cancel my order")
                add("Track tickets", chat="Track my tickets")
                add("My cart", chat="Show my cart")
            add("Black shirts", chat="Recommend black shirts")
            add("Trending", chat="Show trending products")
            add("Raise ticket", ticket="Please raise a ticket - I need help with my order")

        return actions[:4]

    def _format_recent_orders(self, orders: list[Order]) -> str:
        if not orders:
            return "I couldn’t find any orders under your account right now. If you recently placed one, please share the Order ID and I’ll check it for you."

        lines = ["Sure — here are your latest 3 orders:"]
        for idx, order in enumerate(orders[:3], start=1):
            created = order.created_at.strftime("%d %b %Y") if order.created_at else "recent"
            lines.append(
                f"{idx}. {order.order_number} - {order.status} | Tracking: {order.tracking_id} | ₹{int(order.total_amount)} | {created}"
            )
        lines.append("If you want, just reply with an Order ID or Tracking ID and I’ll share the latest status for that order.")
        return "\n".join(lines)

    def _format_recent_tickets(self, tickets: list[SupportTicket]) -> str:
        if not tickets:
            return "You don’t have any support tickets yet. If you need help with an order, I can create one for you."

        lines = ["Sure — here are your latest 3 support tickets:"]
        for idx, ticket in enumerate(tickets[:3], start=1):
            created = ticket.created_at.strftime("%d %b %Y") if ticket.created_at else "recent"
            order_ref = f" | Order: {ticket.order_number}" if ticket.order_number else ""
            lines.append(
                f"{idx}. {ticket.ticket_number} - {ticket.status}{order_ref} | {created}"
            )
        lines.append("Just reply with a ticket ID if you want the latest detailed update for any one of them.")
        return "\n".join(lines)

    def create_ticket(
        self,
        db: Session,
        user_email: Optional[str],
        subject: str,
        issue: str,
        sentiment: str,
        order_number: Optional[str] = None,
    ):
        ticket = SupportTicket(
            ticket_number=generate_ticket_number(),
            customer_email=user_email or "guest@stylehub.local",
            subject=subject,
            issue=issue,
            order_number=order_number,
            status="Open",
            priority="High" if sentiment == "negative" else "Medium",
            source="Chatbot",
            sentiment=sentiment,
        )
        db.add(ticket)
        db.commit()
        db.refresh(ticket)

        try:
            mongo_service.create_ticket(
                {
                    "ticket_number": ticket.ticket_number,
                    "customer_email": ticket.customer_email,
                    "subject": ticket.subject,
                    "issue": ticket.issue,
                    "order_number": ticket.order_number,
                    "status": ticket.status,
                    "priority": ticket.priority,
                    "sentiment": ticket.sentiment,
                }
            )
        except Exception:
            pass

        return ticket

    def _format_products(self, products: list[Product]) -> str:
        if not products:
            return (
                "I couldn’t find the right matches just yet. "
                "Try something like black shirts, jeans under 2000, or women’s dresses, and I’ll do my best to help."
            )

        lines = []
        for product in products[:4]:
            lines.append(f"{product.name} - ₹{int(product.price)}")

        return "Here are some options you might like:\n" + "\n".join(lines)

    def _get_user_orders(self, db: Session, user_email: str):
        return (
            db.query(Order)
            .join(User, Order.user_id == User.id)
            .filter(User.email == user_email)
            .order_by(Order.created_at.desc())
            .all()
        )

    def _find_ticket_from_query(self, query: str, db: Session):
        for token in query.replace("#", " ").split():
            token = token.upper().strip(".,")
            if token.startswith("TKT"):
                return db.query(SupportTicket).filter(SupportTicket.ticket_number == token).first()
        return None

    def _get_user_tickets(self, db: Session, user_email: str):
        return (
            db.query(SupportTicket)
            .filter(SupportTicket.customer_email == user_email)
            .order_by(SupportTicket.created_at.desc())
            .all()
        )

    def _find_order_from_query(self, query: str, db: Session):
        for token in query.replace("#", " ").split():
            token = token.upper().strip(".,")
            if token.startswith("ORD"):
                return db.query(Order).filter(Order.order_number == token).first()
            if token.startswith("TRK"):
                return db.query(Order).filter(Order.tracking_id == token).first()
        return None

    def _get_user_cart(self, db: Session, user_email: str):
        return (
            db.query(CartItem, Product)
            .join(User, CartItem.user_id == User.id)
            .join(Product, CartItem.product_id == Product.id)
            .filter(User.email == user_email)
            .order_by(CartItem.created_at.desc())
            .all()
        )

    def _format_cart(self, cart_rows) -> str:
        if not cart_rows:
            return "Your cart is currently empty."

        items = []
        subtotal = 0
        total_items = 0
        for cart_item, product in cart_rows:
            line_total = product.price * cart_item.quantity
            subtotal += line_total
            total_items += cart_item.quantity
            items.append(f"- {product.name} x{cart_item.quantity} — ₹{int(line_total)}")

        item_word = "items" if total_items != 1 else "item"
        return (
            f"Here are the items in your cart ({total_items} {item_word}):\n"
            + "\n".join(items)
            + f"\nSubtotal: ₹{int(subtotal)}"
        )

    def _find_user_order(self, db: Session, user_email: Optional[str], order_number: str):
        if not user_email:
            return None
        return (
            db.query(Order)
            .join(User, Order.user_id == User.id)
            .filter(User.email == user_email, Order.order_number == order_number)
            .first()
        )

    def _cancel_order(self, db: Session, order: Order) -> str:
        if order.status == "Cancelled":
            return f"I checked order {order.order_number} for you — it has already been cancelled."

        if order.status == "Delivered":
            return (
                f"I’m sorry, but order {order.order_number} has already been delivered, "
                "so it can’t be cancelled now. If you’d like, I can help you with a return request instead."
            )

        order.status = "Cancelled"
        order.cancel_reason = "Cancelled via chatbot"

        if order.payment_method == "Online" and order.payment_status == "Paid":
            order.payment_status = "Refund Initiated"

        for item in order.items:
            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product:
                product.stock += item.quantity

        db.commit()
        refund_note = " Refund has been initiated as well." if order.payment_method == "Online" and order.payment_status == "Refund Initiated" else ""
        return (
            f"Done — I’ve cancelled order {order.order_number} for you. "
            f"Its current status is now {order.status}.{refund_note}"
        )

    def answer(
        self,
        query: str,
        db: Session,
        user_email: Optional[str] = None,
        history=None,
        current_product_id=None,
    ):
        history = history or []
        q = query.lower().strip()
        sentiment = self.get_sentiment(query)
        ticket_id = None
        context = self._get_context(user_email)
        response = None

        if history:
            context["history"] = history[-10:]

        if context.get("pending_action") == "cancel_order":
            order = self._find_order_from_query(query, db)
            if not user_email:
                context["pending_action"] = None
                response = "Please log in first, then share your Order ID and I’ll help you cancel it right away."
            elif order and order.order_number:
                user_order = self._find_user_order(db, user_email, order.order_number)
                context["pending_action"] = None
                if user_order:
                    response = self._cancel_order(db, user_order)
                else:
                    response = "I couldn’t find that order under your account. Please double-check the Order ID and send it again."
            else:
                response = "Sure — please send me your Order ID (for example, ORD12345), and I’ll cancel it for you if it’s eligible."

        elif any(word in q.split() for word in ["hello", "hi", "hey", "start"]):
            response = (
                "Hi! I’m here to help just like customer support — I can help you find products, "
                "recommend styles, manage your cart, track orders, cancel eligible orders, and check ticket updates."
            )

        elif "cancel" in q and "ticket" not in q:
            order = self._find_order_from_query(query, db)
            if not user_email:
                response = "I can help with that. Please log in first, then send your Order ID so I can cancel the order for you."
            elif order and order.order_number:
                user_order = self._find_user_order(db, user_email, order.order_number)
                if user_order:
                    response = self._cancel_order(db, user_order)
                else:
                    response = "I couldn’t find that order under your account. Please share the correct Order ID and I’ll check it right away."
            else:
                context["pending_action"] = "cancel_order"
                response = "Of course — please share your Order ID, and I’ll cancel the order for you if it hasn’t been delivered yet."

        elif self._find_order_from_query(query, db):
            order = self._find_order_from_query(query, db)
            response = (
                f"Sure — I checked order {order.order_number} for you. "
                f"It is currently {order.status}. Tracking ID: {order.tracking_id}. Payment status: {order.payment_status}."
            )

        elif self._find_ticket_from_query(query, db):
            ticket = self._find_ticket_from_query(query, db)
            note = f" Admin note: {ticket.admin_note}." if ticket.admin_note else ""
            response = f"I checked ticket {ticket.ticket_number} for you — it is currently {ticket.status}.{note}"

        elif (
            any(word in q for word in ["show", "find", "search", "looking for", "need", "want"])
            and any(
                word in q
                for word in [
                    "shirt", "shirts", "jeans", "jacket", "jackets", "dress", "dresses",
                    "shoes", "sneakers", "hoodie", "hoodies", "kurta", "kurtas",
                    "women", "men", "black", "white", "blue", "red", "top", "tops"
                ]
            )
        ):
            products = self._find_products(query, db, context)
            response = self._format_products(products)

        elif any(word in q for word in ["under", "below", "less than", "price", "budget", "top rated", "rating"]):
            products = self._find_products(query, db, context)
            response = self._format_products(products)

        elif "recommend" in q or "suggest" in q or "similar" in q:
            searched_products = self._find_products(query, db, context)
            if searched_products:
                response = "Based on your search, here are the best matches\n" + "\n".join(
                    [f"{product.name} - ₹{int(product.price)}" for product in searched_products[:4]]
                )
            else:
                recs = self._recommend_products(db, context, current_product_id=current_product_id)
                if recs:
                    response = "Based on what you’re browsing, here are some good picks\n" + "\n".join(
                        [f"{product.name} - ₹{int(product.price)}" for product in recs]
                    )
                else:
                    response = "I couldn’t find the right recommendations just yet, but I’d be happy to help you narrow it down by category, color, size, or budget."

        elif "trending" in q or "popular" in q:
            products = (
                db.query(Product)
                .order_by(Product.stock.desc(), Product.created_at.desc())
                .limit(4)
                .all()
            )
            if products:
                response = "These are trending right now\n" + "\n".join(
                    [f"{product.name} - ₹{int(product.price)}" for product in products]
                )
            else:
                response = "I couldn’t find trending products right now."

        elif "show my orders" in q or "my orders" in q or "track my orders" in q:
            if not user_email:
                response = "Please log in once, and I’ll show you your orders right away."
            else:
                orders = self._get_user_orders(db, user_email)
                response = self._format_recent_orders(orders)

        elif any(phrase in q for phrase in ["order status", "status of order", "status of orders", "track my delivery", "where is my order", "track my order", "track order", "tracking","where","fast"]):
            order = self._find_order_from_query(query, db)

            if order:
                response = (
                    f"I checked that for you — your order {order.order_number} is currently {order.status}. "
                    f"Tracking ID: {order.tracking_id}."
                )
            elif user_email:
                user_orders = self._get_user_orders(db, user_email)
                response = self._format_recent_orders(user_orders)
            else:
                response = "I can check that for you. Please log in or share your Order ID / Tracking ID, and I’ll look up the latest status."

        elif any(word in q for word in ["raise ticket", "create ticket", "open ticket", "complaint", "issue"]) and "status" not in q:
            order_number = None
            for token in query.replace("#", " ").split():
                token = token.upper().strip(".,")
                if token.startswith("ORD"):
                    order_number = token
                    break

            ticket = self.create_ticket(
                db=db,
                user_email=user_email,
                subject="Customer support request",
                issue=query,
                sentiment=sentiment,
                order_number=order_number,
            )
            ticket_id = ticket.ticket_number
            response = f"I’ve created a support ticket for you. Your ticket ID is {ticket.ticket_number}. Our team can now track this properly for you."

        elif "ticket status" in q or ("status" in q and "ticket" in q):
            ticket = self._find_ticket_from_query(query, db)

            if ticket:
                note = f" Admin note: {ticket.admin_note}." if ticket.admin_note else ""
                response = f"I checked ticket {ticket.ticket_number} for you — it is currently {ticket.status}.{note}"
            elif user_email:
                tickets = self._get_user_tickets(db, user_email)
                response = self._format_recent_tickets(tickets)
            else:
                response = "I can check that for you. Please log in or share your ticket ID, and I’ll pull the latest update."

        elif "ticket history" in q or "my tickets" in q or "track my tickets" in q or q.strip() == "tickets":
            if not user_email:
                response = "Please log in once, and I’ll show you your ticket history."
            else:
                tickets = self._get_user_tickets(db, user_email)
                response = self._format_recent_tickets(tickets)

        elif "return policy" in q or "exchange policy" in q or "return" in q:
            response = "Sure — unused items can be returned or exchanged within 7 days of delivery, as long as the tags are still attached.Go to My Orders, select the order you want to return, and click on the Return button."

        elif "refund" in q:
            response = "Of course — once the returned item is verified, the refund is processed. It usually reflects within a few business days depending on your payment method."

        elif "shipping" in q or "delivery time" in q:
            response = "Standard delivery usually takes 3 to 6 business days, and express delivery is available in selected locations. If you share an order ID, I can help you check a specific order too."

        elif "payment" in q or "upi" in q or "card" in q or "cod" in q:
            response = "We support UPI, debit cards, credit cards, net banking, and Cash on Delivery in eligible locations. If you need help during checkout, I’m here for that too."

        elif "show my cart" in q or "my cart" in q or q == "cart":
            if not user_email:
                response = "Please log in once, and I’ll show you everything currently in your cart."
            else:
                cart_rows = self._get_user_cart(db, user_email)
                response = self._format_cart(cart_rows)

        elif "add this product to cart" in q or "add to cart" in q:
            if current_product_id:
                response = "You can add this item using the Add to Cart button on the product page. If you want, I can also help you find similar options before you decide."
            else:
                response = "Please open a product first and use Add to Cart there. If you’d like, I can help you find the right item based on style, color, or budget."

        elif "remove item from cart" in q or "remove from cart" in q or "remove" in q:
            response = "You can remove items directly from the cart page. If you want, I can also help you review what’s currently in your cart first."

        elif "wishlist" in q or "save for later" in q or "add to wishlist" in q:
            if current_product_id:
                response = "You can save this item to your wishlist directly from the product page."
            else:
                response = "You can add products to your wishlist from any product page, and come back to them later whenever you want."

        elif "checkout" in q:
            response = "Once your items are in the cart, you can continue to checkout from the cart page. If anything feels confusing there, I can guide you."

        elif "cart page" in q:
            response = "You can open the cart page to review your items, update quantities, and continue to checkout whenever you’re ready."

        elif "wishlist page" in q:
            response = "You can open your wishlist page anytime to view all your saved items."

        else:
            response = (
                "I’m here to help with shopping support — I can find products, suggest styles, check cart items, "
                "track or cancel orders, check ticket status, and answer your questions like a customer care assistant."
            )

        try:
            mongo_service.log_chat(
                {
                    "user_email": user_email or "guest",
                    "message": query,
                    "response": response,
                    "sentiment": sentiment,
                    "ticket_id": ticket_id,
                }
            )
        except Exception:
            pass

        return {
            "response": response,
            "sentiment": sentiment,
            "ticket_id": ticket_id,
            "quick_actions": self._build_quick_actions(query, user_email, context),
        }



chatbot = SupportChatbot()
