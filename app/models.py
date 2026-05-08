from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(150), unique=True, nullable=False, index=True)
    phone = Column(String(20), nullable=True)
    password_hash = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    orders = relationship("Order", back_populates="user")
    cart_items = relationship("CartItem", back_populates="user", cascade="all, delete-orphan")
    wishlist_items = relationship("WishlistItem", back_populates="user", cascade="all, delete-orphan")


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String(40), unique=True, nullable=False)
    name = Column(String(150), nullable=False)
    category = Column(String(80), nullable=False)
    description = Column(Text, nullable=False)
    price = Column(Float, nullable=False)
    stock = Column(Integer, default=0)
    image = Column(String(255), nullable=False)
    sizes = Column(String(100), default="S,M,L,XL")
    created_at = Column(DateTime, default=datetime.utcnow)


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String(40), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    customer_name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False)
    address = Column(Text, nullable=False)
    city = Column(String(80), nullable=False)
    state = Column(String(80), nullable=False)
    pincode = Column(String(20), nullable=False)
    status = Column(String(40), default="Processing")
    tracking_id = Column(String(40), nullable=False)
    total_amount = Column(Float, nullable=False)
    payment_method = Column(String(30), default="COD")
    payment_status = Column(String(30), default="Pending")
    payment_reference = Column(String(60), nullable=True)
    cancel_reason = Column(Text, nullable=True)
    return_status = Column(String(30), default="Not Requested")
    created_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    product_name = Column(String(150), nullable=False)
    size = Column(String(20), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    order = relationship("Order", back_populates="items")


class SupportTicket(Base):
    __tablename__ = "support_tickets"
    id = Column(Integer, primary_key=True, index=True)
    ticket_number = Column(String(40), unique=True, nullable=False, index=True)
    customer_email = Column(String(150), nullable=False)
    subject = Column(String(200), nullable=False)
    issue = Column(Text, nullable=False)
    order_number = Column(String(40), nullable=True)
    status = Column(String(30), default="Open")
    priority = Column(String(20), default="Medium")
    source = Column(String(30), default="Chatbot")
    sentiment = Column(String(20), default="neutral")
    admin_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class CartItem(Base):
    __tablename__ = "cart_items"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    quantity = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User", back_populates="cart_items")


class WishlistItem(Base):
    __tablename__ = "wishlist_items"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User", back_populates="wishlist_items")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(500), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_revoked = Column(Boolean, default=False)
    user = relationship("User")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    id = Column(Integer, primary_key=True, index=True)
    token = Column(String(500), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_used = Column(Boolean, default=False)
    user = relationship("User")


class Session(Base):
    __tablename__ = "sessions"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(500), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)
    device_type = Column(String(50), nullable=True)
    browser = Column(String(100), nullable=True)
    location = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True)
    last_activity = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User")


class UserActivity(Base):
    __tablename__ = "user_activities"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    activity_type = Column(String(50), nullable=False)
    activity_details = Column(Text, nullable=True)
    page_url = Column(String(500), nullable=True)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User")


class UserAlert(Base):
    __tablename__ = "user_alerts"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    alert_type = Column(String(50), nullable=False)
    title = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    order_id = Column(String(100), nullable=True)
    is_read = Column(Boolean, default=False)
    priority = Column(String(20), default="medium")
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    action_url = Column(String(500), nullable=True)
    meta_data = Column(Text, nullable=True)
    user = relationship("User")
    product = relationship("Product")


class AdminDocument(Base):
    __tablename__ = "admin_documents"
    
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(String(100), unique=True, nullable=False)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    document_type = Column(String(50), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=True)
    mime_type = Column(String(100), nullable=True)
    ocr_text = Column(Text, nullable=True)
    extracted_data = Column(Text, nullable=True)
    search_index_id = Column(String(100), nullable=True)
    embedding_id = Column(String(100), nullable=True)
    uploaded_by = Column(Integer, nullable=False)
    status = Column(String(50), default="pending")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(100), nullable=True)
    old_values = Column(Text, nullable=True)
    new_values = Column(Text, nullable=True)
    ip_address = Column(String(50), nullable=True)
    user_agent = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class SystemSettings(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    setting_key = Column(String(100), unique=True, nullable=False, index=True)
    setting_value = Column(Text, nullable=True)
    setting_type = Column(String(20), default="string")  # string, int, bool, json
    description = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(Integer, ForeignKey("users.id"), nullable=True)
