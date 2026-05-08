from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

from fastapi import APIRouter, Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from sqlalchemy import func, case
from sqlalchemy.orm import Session, selectinload

from app.auth import (
    create_access_token,
    create_password_reset_token,
    create_refresh_token,
    create_user_session,
    get_current_user,
    get_user_analytics,
    get_user_sessions,
    hash_password,
    log_user_activity,
    mark_password_reset_token_used,
    revoke_all_sessions,
    revoke_refresh_token,
    revoke_session,
    verify_password,
    verify_password_reset_token,
    verify_refresh_token,
)
from app.config import settings
from app.database import get_db
from app.models import CartItem, Order, OrderItem, Product, SupportTicket, User, WishlistItem, AdminDocument, UserActivity, AuditLog, Session as UserSession, SystemSettings
from app.services.agent_flow import agent_graph
from app.services.chatbot import chatbot
from app.services.mongo_service import mongo_service
from app.services.rag_service import KB_DIR, rag_service
from app.services.product_search_service import product_search_service
from app.services.customer_support_agent import customer_support_agent
from app.services.document_search_service import user_document_search_service
from app.services.order_insights_service import order_insights_service
from app.services.customer_segmentation_service import customer_segmentation_service
from app.services.behavior_analysis_service import behavior_analysis_service
from app.services.personalization_service import personalization_service
from app.services.user_alerts_service import user_alerts_service
from app.services.admin_analytics_service import admin_analytics_service
from app.services.demand_forecasting_service import demand_forecasting_service
from app.services.anomaly_detection_service import anomaly_detection_service
from app.services.multi_agent_service import multi_agent_center, InventoryAgent
from app.services.ai_multi_agent_service import ai_multi_agent_center
from app.services.user_management_service import user_management_service
from app.services.document_intelligence_panel_service import document_intelligence_service
from app.services.azure_management_service import azure_management_service
from app.services.data_engineering_service import data_engineering_service
from app.services.powerbi_service import powerbi_service
from app.email_service import send_password_reset_email
from app.utils import create_payment_reference, create_session_token, generate_order_number, generate_tracking_id

# Initialize logger
logger = logging.getLogger(__name__)

router = APIRouter()

# Create custom Jinja2 environment without caching to avoid "unhashable type: dict" error
env = Environment(
    loader=FileSystemLoader("app/templates"),
    autoescape=select_autoescape(['html', 'xml']),
    auto_reload=False,
    cache_size=0  # Disable caching
)

class CustomJinja2Templates:
    def __init__(self, env):
        self.env = env
    
    def TemplateResponse(self, name, context):
        from fastapi.responses import HTMLResponse
        template = self.env.get_template(name)
        return HTMLResponse(template.render(context))

templates = CustomJinja2Templates(env)

BASE_DIR = Path(__file__).resolve().parents[2]
UPLOAD_DIR = BASE_DIR / "app" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ORDER_TIMELINE = ["Confirmed", "Packed", "Shipped", "Out for Delivery", "Delivered", "Returned"]


def search_visual_matches(db: Session, query: str):
    q = query.lower().replace("-", " ").replace("_", " ")
    tokens = [token for token in q.split() if token]
    products = db.query(Product).all()
    scored = []

    for product in products:
        hay = f"{product.name} {product.category} {product.description}".lower()
        score = sum(2 for t in tokens if t in hay)
        if score:
            scored.append((score, product))

    scored.sort(key=lambda x: (-x[0], x[1].price))
    return [product for _, product in scored[:6]]


def get_recommended_products(db: Session, limit: int = 4):
    return db.query(Product).order_by(Product.stock.desc(), Product.created_at.desc()).limit(limit).all()


def _timeline_payload(status: str):
    normalized = status if status in ORDER_TIMELINE else "Confirmed"
    active_index = ORDER_TIMELINE.index(normalized)
    return [
        {
            "label": step,
            "done": idx <= active_index,
            "active": idx == active_index,
        }
        for idx, step in enumerate(ORDER_TIMELINE)
    ]


def _cart_items(db: Session, user_id: int):
    return (
        db.query(CartItem, Product)
        .join(Product, CartItem.product_id == Product.id)
        .filter(CartItem.user_id == user_id)
        .all()
    )


def _create_order_from_cart(
    db: Session,
    user: User,
    items: list[tuple[CartItem, Product]],
    customer_name: str,
    phone: str,
    address: str,
    city: str,
    state: str,
    pincode: str,
    payment_method: str,
):
    if not items:
        raise HTTPException(status_code=400, detail="Your cart is empty")

    for cart_item, product in items:
        if product.stock < cart_item.quantity:
            raise HTTPException(status_code=400, detail=f"Insufficient stock for {product.name}")

    payment_method = payment_method if payment_method in {"COD", "Online"} else "COD"
    payment_status = "Paid" if payment_method == "Online" else "Pending"
    payment_reference = create_payment_reference() if payment_method == "Online" else None
    total_amount = sum(cart_item.quantity * product.price for cart_item, product in items)

    order = Order(
        order_number=generate_order_number(),
        user_id=user.id,
        customer_name=customer_name,
        phone=phone,
        address=address,
        city=city,
        state=state,
        pincode=pincode,
        status="Confirmed",
        tracking_id=generate_tracking_id(),
        total_amount=total_amount,
        payment_method=payment_method,
        payment_status=payment_status,
        payment_reference=payment_reference,
    )
    db.add(order)
    db.flush()

    for cart_item, product in items:
        db.add(
            OrderItem(
                order_id=order.id,
                product_id=product.id,
                product_name=product.name,
                size="Standard",
                quantity=cart_item.quantity,
                unit_price=product.price,
            )
        )
        product.stock -= cart_item.quantity
        db.delete(cart_item)

    db.commit()
    db.refresh(order)
    return order


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    products = db.query(Product).order_by(Product.created_at.desc()).all()
    
    # Simplified without search features due to ChromaDB issues
    recommended = get_recommended_products(db, 4)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "products": products,
            "visual_query": "",
            "visual_results": [],
            "search_query": "",
            "semantic_results": [],
            "recommended": recommended,
            "user": user,
            "current_product_id": None,
        },
    )


@router.post("/visual-search/upload", response_class=HTMLResponse)
async def visual_search_upload(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)

    raw_name = (file.filename or "upload").lower()
    safe_name = raw_name.replace(" ", "_")
    save_path = UPLOAD_DIR / safe_name

    content = await file.read()
    save_path.write_bytes(content)

    visual_query = Path(raw_name).stem.replace("_", " ").replace("-", " ")
    products = db.query(Product).order_by(Product.created_at.desc()).all()
    visual_results = search_visual_matches(db, visual_query)
    recommended = get_recommended_products(db, 4)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "products": products,
            "visual_query": visual_query,
            "visual_results": visual_results,
            "recommended": recommended,
            "user": user,
            "uploaded_image": f"/app/uploads/{safe_name}",
            "current_product_id": None,
        },
    )


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": None,
            "user": None,
            "current_product_id": None,
        },
    )


@router.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()

    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "error": "Invalid email or password",
                "user": None,
                "current_product_id": None,
            },
        )

    session_id = create_user_session(user.id, request, db)
    refresh_token = create_refresh_token(user.id, db)
    
    token = create_session_token({"user_id": user.id, "is_admin": user.is_admin, "session_id": session_id})
    redirect_url = "/admin" if user.is_admin else "/"
    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie("session_token", token, httponly=True)
    response.set_cookie("refresh_token", refresh_token, httponly=True, max_age=604800)
    
    log_user_activity(user.id, "login", db, request=request)
    
    return response


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse(
        "register.html",
        {
            "request": request,
            "error": None,
            "user": None,
            "current_product_id": None,
        },
    )


@router.post("/register")
def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    if db.query(User).filter(User.email == email).first():
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "error": "Email already exists",
                "user": None,
                "current_product_id": None,
            },
        )

    user = User(
        name=name,
        email=email,
        phone=phone,
        password_hash=hash_password(password),
        is_admin=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    session_id = create_user_session(user.id, request, db)
    refresh_token = create_refresh_token(user.id, db)
    
    token = create_session_token({"user_id": user.id, "is_admin": False, "session_id": session_id})
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie("session_token", token, httponly=True)
    response.set_cookie("refresh_token", refresh_token, httponly=True, max_age=604800)
    
    log_user_activity(user.id, "register", db, request=request)
    
    return response


@router.get("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        token = request.cookies.get("session_token")
        if token:
            from app.utils import read_session_token
            payload = read_session_token(token)
            if payload:
                session_id = payload.get("session_id")
                if session_id:
                    revoke_session(session_id, db)
        
        refresh_token = request.cookies.get("refresh_token")
        if refresh_token:
            revoke_refresh_token(refresh_token, db)
        
        log_user_activity(user.id, "logout", db, request=request)
    
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("session_token")
    response.delete_cookie("refresh_token")
    return response


@router.post("/api/refresh-token")
def refresh_token(request: Request, db: Session = Depends(get_db)):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token missing")
    
    user_id = verify_refresh_token(refresh_token, db)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    session_id = create_user_session(user.id, request, db)
    new_refresh_token = create_refresh_token(user.id, db)
    revoke_refresh_token(refresh_token, db)
    
    new_access_token = create_session_token({"user_id": user.id, "is_admin": user.is_admin, "session_id": session_id})
    
    response = JSONResponse({"access_token": new_access_token, "token_type": "bearer"})
    response.set_cookie("session_token", new_access_token, httponly=True)
    response.set_cookie("refresh_token", new_refresh_token, httponly=True, max_age=604800)
    
    log_user_activity(user.id, "token_refresh", db, request=request)
    
    return response


@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request):
    return templates.TemplateResponse(
        "forgot_password.html",
        {
            "request": request,
            "error": None,
            "success": None,
            "user": None,
            "current_product_id": None,
        },
    )


@router.post("/forgot-password")
def forgot_password(request: Request, email: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email).first()
    
    if user:
        reset_token = create_password_reset_token(user.id, db)
        email_sent = send_password_reset_email(user.email, reset_token, user.name)
        
        if email_sent:
            return templates.TemplateResponse(
                "forgot_password.html",
                {
                    "request": request,
                    "error": None,
                    "success": "Password reset link has been sent to your email",
                    "user": None,
                    "current_product_id": None,
                },
            )
        else:
            return templates.TemplateResponse(
                "forgot_password.html",
                {
                    "request": request,
                    "error": "Failed to send email. Please try again later.",
                    "success": None,
                    "user": None,
                    "current_product_id": None,
                },
            )
    
    return templates.TemplateResponse(
        "forgot_password.html",
        {
            "request": request,
            "error": "If an account with this email exists, a reset link has been sent.",
            "success": None,
            "user": None,
            "current_product_id": None,
        },
    )


@router.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(request: Request, token: str, db: Session = Depends(get_db)):
    user_id = verify_password_reset_token(token, db)
    
    if not user_id:
        return templates.TemplateResponse(
            "reset_password.html",
            {
                "request": request,
                "error": "Invalid or expired reset token",
                "success": None,
                "token": None,
                "user": None,
                "current_product_id": None,
            },
        )
    
    return templates.TemplateResponse(
        "reset_password.html",
        {
            "request": request,
            "error": None,
            "success": None,
            "token": token,
            "user": None,
            "current_product_id": None,
        },
    )


@router.post("/reset-password")
def reset_password(
    request: Request,
    token: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    if new_password != confirm_password:
        return templates.TemplateResponse(
            "reset_password.html",
            {
                "request": request,
                "error": "Passwords do not match",
                "success": None,
                "token": token,
                "user": None,
                "current_product_id": None,
            },
        )
    
    user_id = verify_password_reset_token(token, db)
    if not user_id:
        return templates.TemplateResponse(
            "reset_password.html",
            {
                "request": request,
                "error": "Invalid or expired reset token",
                "success": None,
                "token": None,
                "user": None,
                "current_product_id": None,
            },
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return templates.TemplateResponse(
            "reset_password.html",
            {
                "request": request,
                "error": "User not found",
                "success": None,
                "token": None,
                "user": None,
                "current_product_id": None,
            },
        )
    
    user.password_hash = hash_password(new_password)
    mark_password_reset_token_used(token, db)
    
    revoke_all_sessions(user_id, db)
    
    log_user_activity(user_id, "password_reset", db, request=request)
    
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "error": None,
            "success": "Password has been reset successfully. Please login with your new password.",
            "user": None,
            "current_product_id": None,
        },
    )


@router.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    
    sessions = get_user_sessions(user.id, db)
    analytics = get_user_analytics(user.id, db)
    
    return templates.TemplateResponse(
        "profile.html",
        {
            "request": request,
            "user": user,
            "sessions": sessions,
            "analytics": analytics,
            "current_product_id": None,
        },
    )


@router.post("/profile/update")
def profile_update(
    request: Request,
    name: str = Form(...),
    phone: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    
    user.name = name
    user.phone = phone
    db.commit()
    
    log_user_activity(user.id, "profile_update", db, activity_details="Updated profile information", request=request)
    
    return RedirectResponse(url="/profile", status_code=302)


@router.post("/profile/change-password")
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    
    if not verify_password(current_password, user.password_hash):
        sessions = get_user_sessions(user.id, db)
        analytics = get_user_analytics(user.id, db)
        return templates.TemplateResponse(
            "profile.html",
            {
                "request": request,
                "user": user,
                "sessions": sessions,
                "analytics": analytics,
                "error": "Current password is incorrect",
                "current_product_id": None,
            },
        )
    
    if new_password != confirm_password:
        sessions = get_user_sessions(user.id, db)
        analytics = get_user_analytics(user.id, db)
        return templates.TemplateResponse(
            "profile.html",
            {
                "request": request,
                "user": user,
                "sessions": sessions,
                "analytics": analytics,
                "error": "New passwords do not match",
                "current_product_id": None,
            },
        )
    
    user.password_hash = hash_password(new_password)
    db.commit()
    
    revoke_all_sessions(user.id, db)
    
    log_user_activity(user.id, "password_change", db, activity_details="Changed password", request=request)
    
    return RedirectResponse(url="/login", status_code=302)


@router.post("/profile/sessions/revoke/{session_id}")
def revoke_user_session(request: Request, session_id: str, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    
    session = db.query(UserSession).filter(
        UserSession.session_id == session_id,
        UserSession.user_id == user.id
    ).first()
    
    if session:
        revoke_session(session_id, db)
        log_user_activity(user.id, "session_revoke", db, activity_details=f"Revoked session {session_id}", request=request)
    
    return RedirectResponse(url="/profile", status_code=302)


@router.post("/profile/sessions/revoke-all")
def revoke_all_user_sessions(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    
    token = request.cookies.get("session_token")
    current_session_id = None
    if token:
        from app.utils import read_session_token
        payload = read_session_token(token)
        if payload:
            current_session_id = payload.get("session_id")
    
    revoked_count = revoke_all_sessions(user.id, db, except_session_id=current_session_id)
    
    log_user_activity(user.id, "sessions_revoke_all", db, activity_details=f"Revoked {revoked_count} sessions", request=request)
    
    return RedirectResponse(url="/profile", status_code=302)


@router.get("/product/{product_id}", response_class=HTMLResponse)
def product_detail(request: Request, product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    user = get_current_user(request, db)
    
    # AI-powered similar products
    similar_products = product_search_service.get_similar_products(product_id, n_results=4, db=db)
    if not similar_products:
        similar_products = db.query(Product).filter(Product.category == product.category, Product.id != product.id).limit(4).all()
    
    # AI-powered frequently bought together
    frequently_bought = product_search_service.get_frequently_bought_together(product_id, db, limit=4)
    
    recommendations = similar_products or db.query(Product).filter(Product.id != product_id).limit(4).all()

    return templates.TemplateResponse(
        "product.html",
        {
            "request": request,
            "product": product,
            "recommendations": recommendations,
            "similar_products": similar_products,
            "frequently_bought": frequently_bought,
            "user": user,
            "current_product_id": product.id,
        },
    )


@router.post("/checkout")
def checkout(
    request: Request,
    product_id: int = Form(...),
    quantity: int = Form(...),
    size: str = Form(...),
    customer_name: str = Form(...),
    phone: str = Form(...),
    address: str = Form(...),
    city: str = Form(...),
    state: str = Form(...),
    pincode: str = Form(...),
    payment_method: str = Form("COD"),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product or product.stock < quantity:
        raise HTTPException(status_code=400, detail="Product unavailable or insufficient stock")

    payment_method = payment_method if payment_method in {"COD", "Online"} else "COD"
    payment_status = "Paid" if payment_method == "Online" else "Pending"
    payment_reference = create_payment_reference() if payment_method == "Online" else None

    order = Order(
        order_number=generate_order_number(),
        user_id=user.id,
        customer_name=customer_name,
        phone=phone,
        address=address,
        city=city,
        state=state,
        pincode=pincode,
        status="Confirmed",
        tracking_id=generate_tracking_id(),
        total_amount=product.price * quantity,
        payment_method=payment_method,
        payment_status=payment_status,
        payment_reference=payment_reference,
    )
    db.add(order)
    db.flush()

    db.add(
        OrderItem(
            order_id=order.id,
            product_id=product.id,
            product_name=product.name,
            size=size,
            quantity=quantity,
            unit_price=product.price,
        )
    )

    product.stock -= quantity

    existing_cart = db.query(CartItem).filter_by(user_id=user.id, product_id=product.id).first()
    if existing_cart:
        db.delete(existing_cart)

    db.commit()
    return RedirectResponse(url=f"/orders/{order.order_number}", status_code=302)


@router.get("/cart", response_class=HTMLResponse)
def cart_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    items = _cart_items(db, user.id)
    total = sum(ci.quantity * p.price for ci, p in items)

    return templates.TemplateResponse(
        "cart.html",
        {
            "request": request,
            "user": user,
            "items": items,
            "total": total,
            "current_product_id": None,
        },
    )


@router.post("/cart/add/{product_id}")
def cart_add(request: Request, product_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    item = db.query(CartItem).filter_by(user_id=user.id, product_id=product_id).first()
    if item:
        item.quantity += 1
    else:
        db.add(CartItem(user_id=user.id, product_id=product_id, quantity=1))

    db.commit()
    return RedirectResponse(url="/cart", status_code=302)


@router.post("/cart/remove/{product_id}")
def cart_remove(request: Request, product_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    item = db.query(CartItem).filter_by(user_id=user.id, product_id=product_id).first()
    if item:
        db.delete(item)
        db.commit()

    return RedirectResponse(url="/cart", status_code=302)


@router.post("/cart/checkout")
def cart_checkout(
    request: Request,
    customer_name: str = Form(...),
    phone: str = Form(...),
    address: str = Form(...),
    city: str = Form(...),
    state: str = Form(...),
    pincode: str = Form(...),
    payment_method: str = Form("COD"),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    items = _cart_items(db, user.id)
    order = _create_order_from_cart(
        db=db,
        user=user,
        items=items,
        customer_name=customer_name,
        phone=phone,
        address=address,
        city=city,
        state=state,
        pincode=pincode,
        payment_method=payment_method,
    )
    return RedirectResponse(url=f"/orders/{order.order_number}", status_code=302)


@router.get("/wishlist", response_class=HTMLResponse)
def wishlist_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    items = (
        db.query(WishlistItem, Product)
        .join(Product, WishlistItem.product_id == Product.id)
        .filter(WishlistItem.user_id == user.id)
        .all()
    )

    return templates.TemplateResponse(
        "wishlist.html",
        {
            "request": request,
            "user": user,
            "items": items,
            "current_product_id": None,
        },
    )


@router.post("/wishlist/add/{product_id}")
def wishlist_add(request: Request, product_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    item = db.query(WishlistItem).filter_by(user_id=user.id, product_id=product_id).first()
    if not item:
        db.add(WishlistItem(user_id=user.id, product_id=product_id))
        db.commit()

    return RedirectResponse(url="/wishlist", status_code=302)


@router.post("/wishlist/remove/{product_id}")
def wishlist_remove(request: Request, product_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    item = db.query(WishlistItem).filter_by(user_id=user.id, product_id=product_id).first()
    if item:
        db.delete(item)
        db.commit()

    return RedirectResponse(url="/wishlist", status_code=302)


@router.post("/orders/{order_number}/cancel")
def cancel_order(
    request: Request,
    order_number: str,
    cancel_reason: str = Form("Cancelled by customer"),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    order = db.query(Order).filter(Order.order_number == order_number, Order.user_id == user.id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status in {"Delivered", "Cancelled"}:
        return RedirectResponse(url=f"/orders/{order.order_number}", status_code=302)

    order.status = "Cancelled"
    order.cancel_reason = cancel_reason

    if order.payment_method == "Online" and order.payment_status == "Paid":
        order.payment_status = "Refund Initiated"

    for item in order.items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        if product:
            product.stock += item.quantity

    db.commit()
    return RedirectResponse(url=f"/orders/{order.order_number}", status_code=302)

@router.post("/orders/{order_number}/return")
def return_order(request: Request, order_number: str, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    order = db.query(Order).filter(
        Order.order_number == order_number,
        Order.user_id == user.id
    ).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status != "Delivered":
        return RedirectResponse(url=f"/orders/{order.order_number}", status_code=302)

    if order.return_status != "Not Requested":
        return RedirectResponse(url=f"/orders/{order.order_number}", status_code=302)

    order.return_status = "Return Requested"

    if order.payment_method == "Online" and order.payment_status == "Paid":
        order.payment_status = "Refund Initiated"

    db.commit()
    return RedirectResponse(url=f"/orders/{order.order_number}", status_code=302)

@router.get("/orders", response_class=HTMLResponse)
def orders(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    orders = db.query(Order).filter(Order.user_id == user.id).options(selectinload(Order.items)).order_by(Order.created_at.desc()).all()

    return templates.TemplateResponse(
        "orders.html",
        {
            "request": request,
            "orders": orders,
            "user": user,
            "current_product_id": None,
        },
    )


@router.get("/orders/{order_number}", response_class=HTMLResponse)
def order_detail(request: Request, order_number: str, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    order = db.query(Order).filter(Order.order_number == order_number, Order.user_id == user.id).options(selectinload(Order.items)).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return templates.TemplateResponse(
        "order_detail.html",
        {
            "request": request,
            "order": order,
            "user": user,
            "timeline": _timeline_payload("Returned" if getattr(order, "return_status", "") == "Returned" else order.status),
            "current_product_id": None,
        },
    )


@router.get("/orders/{order_number}/invoice.txt")
def invoice_download(request: Request, order_number: str, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    order = db.query(Order).filter(Order.order_number == order_number, Order.user_id == user.id).options(selectinload(Order.items)).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    lines = [
        "STYLEHUB AI STORE INVOICE",
        f"Order Number: {order.order_number}",
        f"Tracking ID: {order.tracking_id}",
        f"Customer: {order.customer_name}",
        f"Phone: {order.phone}",
        f"Address: {order.address}, {order.city}, {order.state} - {order.pincode}",
        f"Status: {order.status}",
        f"Payment Method: {order.payment_method}",
        f"Payment Status: {order.payment_status}",
        "",
        "Items:",
    ]

    for item in order.items:
        lines.append(
            f"- {item.product_name} | Size: {item.size} | Qty: {item.quantity} | Amount: ₹{item.unit_price * item.quantity:.0f}"
        )

    lines.extend(["", f"Total Amount: ₹{order.total_amount:.0f}"])

    return PlainTextResponse(
        "\n".join(lines),
        headers={"Content-Disposition": f'attachment; filename="invoice_{order.order_number}.txt"'},
    )


@router.post("/api/chat")
def chat_api(request: Request, payload: dict, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    query = payload.get("message", "")
    history = payload.get("history") or []
    current_product_id = payload.get("current_product_id")

    if agent_graph:
        try:
            agent_graph.invoke({"query": query, "intent": ""})
        except Exception:
            pass

    result = chatbot.answer(
        query,
        db,
        user.email if user else None,
        history,
        current_product_id,
    )
    return JSONResponse(result)


@router.post("/api/raise-ticket")
def raise_ticket_api(request: Request, payload: dict, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    email = user.email if user else payload.get("email") or "guest@stylehub.local"
    message = payload.get("message", "Need support")

    result = customer_support_agent.answer(
        f"raise ticket {message}",
        db,
        email,
        payload.get("history") or [],
        payload.get("current_product_id"),
    )
    return JSONResponse(result)


@router.post("/api/search")
def semantic_search_api(request: Request, payload: dict, db: Session = Depends(get_db)):
    """AI-powered semantic product search API"""
    query = payload.get("query", "")
    n_results = payload.get("n_results", 10)
    
    if not query:
        return JSONResponse({"products": [], "error": "Query is required"})
    
    # Index products if not already indexed
    product_search_service.index_products(db)
    
    # Perform semantic search
    results = product_search_service.semantic_search(query, n_results=n_results, db=db)
    
    # Get full product details
    product_ids = [r["id"] for r in results]
    products = db.query(Product).filter(Product.id.in_(product_ids)).all()
    
    # Add similarity scores
    product_dict = {p.id: p for p in products}
    enhanced_results = []
    for result in results:
        if result["id"] in product_dict:
            product = product_dict[result["id"]]
            enhanced_results.append({
                "id": product.id,
                "name": product.name,
                "category": product.category,
                "description": product.description,
                "price": product.price,
                "stock": product.stock,
                "image": product.image,
                "similarity_score": result["similarity_score"]
            })
    
    return JSONResponse({"products": enhanced_results})


@router.get("/api/recommendations")
def personalized_recommendations_api(request: Request, db: Session = Depends(get_db)):
    """Get personalized recommendations based on user history"""
    user = get_current_user(request, db)
    
    if not user:
        return JSONResponse({"products": [], "error": "User not authenticated"})
    
    recommendations = product_search_service.get_personalized_recommendations(user.id, db, limit=8)
    
    results = []
    for product in recommendations:
        results.append({
            "id": product.id,
            "name": product.name,
            "category": product.category,
            "description": product.description,
            "price": product.price,
            "stock": product.stock,
            "image": product.image
        })
    
    return JSONResponse({"products": results})


@router.get("/api/similar-products/{product_id}")
def similar_products_api(product_id: int, request: Request, db: Session = Depends(get_db)):
    """Get similar products using AI-powered vector similarity"""
    similar_products = product_search_service.get_similar_products(product_id, n_results=6, db=db)
    
    results = []
    for product in similar_products:
        results.append({
            "id": product.id,
            "name": product.name,
            "category": product.category,
            "description": product.description,
            "price": product.price,
            "stock": product.stock,
            "image": product.image
        })
    
    return JSONResponse({"products": results})


@router.get("/api/frequently-bought-together/{product_id}")
def frequently_bought_together_api(product_id: int, db: Session = Depends(get_db)):
    """Get products frequently bought together with the given product"""
    products = product_search_service.get_frequently_bought_together(product_id, db, limit=4)
    
    results = []
    for product in products:
        results.append({
            "id": product.id,
            "name": product.name,
            "category": product.category,
            "description": product.description,
            "price": product.price,
            "stock": product.stock,
            "image": product.image
        })
    
    return JSONResponse({"products": results})


@router.post("/api/smart-filter")
def smart_filter_api(request: Request, payload: dict, db: Session = Depends(get_db)):
    """Smart filtering combining semantic search with metadata filters"""
    query = payload.get("query", "")
    filters = payload.get("filters", {})
    n_results = payload.get("n_results", 20)
    
    # Index products if not already indexed
    product_search_service.index_products(db)
    
    # Perform smart filter
    results = product_search_service.smart_filter(query, filters, db, n_results=n_results)
    
    # Get full product details
    product_ids = [r["id"] for r in results]
    products = db.query(Product).filter(Product.id.in_(product_ids)).all()
    
    # Add similarity scores
    product_dict = {p.id: p for p in products}
    enhanced_results = []
    for result in results:
        if result["id"] in product_dict:
            product = product_dict[result["id"]]
            enhanced_results.append({
                "id": product.id,
                "name": product.name,
                "category": product.category,
                "description": product.description,
                "price": product.price,
                "stock": product.stock,
                "image": product.image,
                "similarity_score": result["similarity_score"]
            })
    
    return JSONResponse({"products": enhanced_results})


@router.post("/api/documents/upload")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(...),
    doc_type: str = Form(...),
    db: Session = Depends(get_db)
):
    """Upload and index a PDF document"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    
    # Save file
    from app.services.document_search_service import USER_DOCS_DIR
    file_path = USER_DOCS_DIR / file.filename
    content = await file.read()
    file_path.write_bytes(content)
    
    # Index the document
    success = user_document_search_service.upload_and_index_pdf(
        file_path,
        title,
        doc_type,
        {"uploaded_by": user.email, "uploaded_at": datetime.utcnow().isoformat()}
    )
    
    if success:
        return JSONResponse({"success": True, "message": "Document indexed successfully"})
    else:
        return JSONResponse({"success": False, "message": "Failed to index document"})


@router.get("/api/documents/search")
def search_documents(request: Request, query: str, doc_type: str = "all", n_results: int = 5):
    """Search indexed documents"""
    if not query:
        return JSONResponse({"results": [], "error": "Query is required"})
    
    if doc_type == "manual":
        results = user_document_search_service.search_manuals(query, n_results=n_results)
    elif doc_type == "policy":
        results = user_document_search_service.search_policies(query, n_results=n_results)
    else:
        results = user_document_search_service.search_all_documents(query, n_results=n_results)
    
    return JSONResponse({"results": results})


@router.get("/api/documents/list")
def list_documents(request: Request, doc_type: str = "all"):
    """List indexed documents"""
    if doc_type == "manual":
        docs = user_document_search_service.get_indexed_documents("manual")
    elif doc_type == "policy":
        docs = user_document_search_service.get_indexed_documents("policy")
    else:
        docs = (
            user_document_search_service.get_indexed_documents("manual") +
            user_document_search_service.get_indexed_documents("policy")
        )
    
    return JSONResponse({"documents": docs})


@router.get("/api/orders/{order_number}/insights")
def get_order_insights(order_number: str, request: Request, db: Session = Depends(get_db)):
    """Get AI-powered insights for an order"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    order = db.query(Order).filter(
        Order.order_number == order_number,
        Order.user_id == user.id
    ).first()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    insights = order_insights_service.get_order_insights(order, db)
    return JSONResponse(insights)


@router.get("/api/orders/{order_number}/delivery-prediction")
def get_delivery_prediction(order_number: str, request: Request, db: Session = Depends(get_db)):
    """Get delivery prediction for an order"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    order = db.query(Order).filter(
        Order.order_number == order_number,
        Order.user_id == user.id
    ).first()
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    estimated_delivery = order_insights_service.predict_delivery_date(order)
    delay_info = order_insights_service.estimate_delay(order)
    
    return JSONResponse({
        "order_number": order.order_number,
        "estimated_delivery": estimated_delivery.isoformat() if estimated_delivery else None,
        "delay_info": delay_info
    })


@router.get("/api/user/analytics")
def api_get_user_analytics(request: Request, db: Session = Depends(get_db)):
    """Get comprehensive user order analytics"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    analytics = order_insights_service.get_user_order_analytics(user.id, db)
    return JSONResponse(analytics)


@router.get("/api/user/notifications")
def get_user_notifications(request: Request, db: Session = Depends(get_db)):
    """Get smart notifications for user's orders"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    notifications = order_insights_service.get_all_user_notifications(user.id, db)
    return JSONResponse({"notifications": notifications})


@router.get("/documents", response_class=HTMLResponse)
def documents_page(request: Request, db: Session = Depends(get_db)):
    """Document search page"""
    user = get_current_user(request, db)
    return templates.TemplateResponse(
        "documents.html",
        {
            "request": request,
            "user": user,
            "current_product_id": None,
        },
    )


@router.get("/order-analytics", response_class=HTMLResponse)
def order_analytics_page(request: Request, db: Session = Depends(get_db)):
    """Order analytics page"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    
    analytics = order_insights_service.get_user_order_analytics(user.id, db)
    notifications = order_insights_service.get_all_user_notifications(user.id, db)
    
    return templates.TemplateResponse(
        "order_analytics.html",
        {
            "request": request,
            "user": user,
            "analytics": analytics,
            "notifications": notifications,
            "current_product_id": None,
        },
    )


@router.get("/api/personalization")
def get_personalization(request: Request, db: Session = Depends(get_db)):
    """Get personalization data for the user"""
    user = get_current_user(request, db)
    if not user:
        return JSONResponse({"error": "Authentication required"})
    
    personalization = personalization_service.get_personalization_data(user.id, db)
    return JSONResponse(personalization)


@router.get("/api/segment")
def get_user_segment(request: Request, db: Session = Depends(get_db)):
    """Get user's customer segment"""
    user = get_current_user(request, db)
    if not user:
        return JSONResponse({"segment": "guest"})
    
    segment = customer_segmentation_service.segment_customer(user.id, db)
    recommendations = customer_segmentation_service.get_segment_recommendations(segment)
    
    return JSONResponse({
        "segment": segment,
        "recommendations": recommendations
    })


@router.get("/api/behavior")
def get_behavior_analysis(request: Request, db: Session = Depends(get_db)):
    """Get user's shopping behavior analysis"""
    user = get_current_user(request, db)
    if not user:
        return JSONResponse({"error": "Authentication required"})
    
    behavior = behavior_analysis_service.get_personalization_insights(user.id, db)
    return JSONResponse(behavior)


@router.get("/api/alerts")
def get_user_alerts(request: Request, unread_only: bool = False, limit: int = 20, db: Session = Depends(get_db)):
    """Get user's alerts"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    alerts = user_alerts_service.get_user_alerts(user.id, db, unread_only=unread_only, limit=limit)
    return JSONResponse({"alerts": alerts})


@router.post("/api/alerts/{alert_id}/read")
def mark_alert_read(alert_id: int, request: Request, db: Session = Depends(get_db)):
    """Mark an alert as read"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    alert = db.query(UserAlert).filter(UserAlert.id == alert_id, UserAlert.user_id == user.id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    success = user_alerts_service.mark_as_read(alert_id, db)
    return JSONResponse({"success": success})


@router.post("/api/alerts/read-all")
def mark_all_alerts_read(request: Request, db: Session = Depends(get_db)):
    """Mark all alerts as read"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    count = user_alerts_service.mark_all_as_read(user.id, db)
    return JSONResponse({"marked_read": count})


@router.delete("/api/alerts/{alert_id}")
def delete_alert(alert_id: int, request: Request, db: Session = Depends(get_db)):
    """Delete an alert"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    alert = db.query(UserAlert).filter(UserAlert.id == alert_id, UserAlert.user_id == user.id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    success = user_alerts_service.delete_alert(alert_id, db)
    return JSONResponse({"success": success})


@router.get("/alerts", response_class=HTMLResponse)
def alerts_page(request: Request, db: Session = Depends(get_db)):
    """Alerts page"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    
    alerts = user_alerts_service.get_user_alerts(user.id, db, limit=50)
    
    return templates.TemplateResponse(
        "alerts.html",
        {
            "request": request,
            "user": user,
            "alerts": alerts,
            "current_product_id": None,
        },
    )


@router.get("/api/admin/analytics")
def get_admin_analytics(request: Request, db: Session = Depends(get_db)):
    """Get comprehensive admin analytics"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    analytics = admin_analytics_service.get_comprehensive_dashboard(db)
    return JSONResponse(analytics)


@router.get("/api/admin/metrics")
def get_admin_metrics(request: Request, db: Session = Depends(get_db)):
    """Get admin dashboard metrics"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    metrics = admin_analytics_service.get_dashboard_metrics(db)
    return JSONResponse(metrics)


@router.get("/api/admin/anomaly-alerts")
def get_anomaly_alerts(request: Request, db: Session = Depends(get_db)):
    """Get anomaly alerts"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    alerts = admin_analytics_service.get_anomaly_alerts(db)
    return JSONResponse({"alerts": alerts})


@router.get("/admin/analytics", response_class=HTMLResponse)
def admin_analytics_page(request: Request, db: Session = Depends(get_db)):
    """Admin analytics dashboard page"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    analytics = admin_analytics_service.get_comprehensive_dashboard(db)
    
    return templates.TemplateResponse(
        "admin_analytics.html",
        {
            "request": request,
            "user": user,
            "analytics": analytics,
            "current_product_id": None,
        },
    )


@router.get("/api/admin/forecast/train")
def train_forecast_models(request: Request, model_type: str = "all", periods: int = 30, db: Session = Depends(get_db)):
    """Train forecasting models and generate forecasts"""
    try:
        user = get_current_user(request, db)
        if not user or not user.is_admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        
        forecasts = demand_forecasting_service.train_and_forecast(db, model_type=model_type, periods=periods)
        return JSONResponse(forecasts)
    except Exception as e:
        import traceback
        error_msg = f"Forecast error: {str(e)}"
        print(error_msg)
        print(traceback.format_exc())
        return JSONResponse({"error": error_msg, "traceback": traceback.format_exc()}, status_code=500)


@router.get("/api/admin/forecast/seasonal")
def get_seasonal_forecast(request: Request, db: Session = Depends(get_db)):
    """Get seasonal forecasting insights"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    seasonal = demand_forecasting_service.get_seasonal_forecast(db)
    return JSONResponse(seasonal)


@router.get("/admin/forecast", response_class=HTMLResponse)
def forecast_dashboard(request: Request, db: Session = Depends(get_db)):
    """Forecast dashboard page"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    return templates.TemplateResponse(
        "forecast_dashboard.html",
        {
            "request": request,
            "user": user,
            "current_product_id": None,
        },
    )


@router.get("/admin/forecast/reports", response_class=HTMLResponse)
def forecast_reports(request: Request, db: Session = Depends(get_db)):
    """Forecast reports page"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    return templates.TemplateResponse(
        "forecast_reports.html",
        {
            "request": request,
            "user": user,
            "current_product_id": None,
        },
    )


@router.get("/admin/forecast/metrics", response_class=HTMLResponse)
def forecast_metrics(request: Request, db: Session = Depends(get_db)):
    """Forecast model metrics page"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    return templates.TemplateResponse(
        "forecast_metrics.html",
        {
            "request": request,
            "user": user,
            "current_product_id": None,
        },
    )


@router.post("/api/admin/forecast/upload-dataset")
async def upload_forecast_dataset(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Upload CSV dataset for forecasting with flexible column mapping"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")
    
    try:
        import io
        import csv
        
        content = await file.read()
        
        # Try different encodings
        decoded_content = None
        for encoding in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']:
            try:
                decoded_content = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        
        if not decoded_content:
            raise HTTPException(status_code=400, detail="Unable to decode CSV file. Please ensure it's saved in UTF-8 format.")
        
        csv_reader = csv.DictReader(io.StringIO(decoded_content))
        
        if not csv_reader.fieldnames:
            raise HTTPException(status_code=400, detail="CSV file has no headers")
        
        # Normalize column names to lowercase
        columns = [col.lower().strip() for col in csv_reader.fieldnames]
        
        # Flexible column mapping
        date_col = None
        revenue_col = None
        orders_col = None
        
        # Try to find date column
        for col in columns:
            if col in ['date', 'datetime', 'time', 'timestamp', 'day']:
                date_col = col
                break
        
        # Try to find revenue column
        for col in columns:
            if col in ['revenue', 'sales', 'amount', 'value', 'price', 'total', 'income']:
                revenue_col = col
                break
        
        # Try to find orders column
        for col in columns:
            if col in ['orders', 'order_count', 'quantity', 'count', 'num_orders']:
                orders_col = col
                break
        
        if not date_col or not revenue_col:
            raise HTTPException(
                status_code=400,
                detail=f"CSV must contain date and revenue columns. Found columns: {', '.join(columns)}. "
                      f"Expected columns like: date, revenue (or: datetime, sales, amount, etc.)"
            )
        
        # Parse CSV data with flexible column mapping
        data = []
        parse_errors = []
        
        for row_num, row in enumerate(csv_reader, start=2):  # Start at 2 (header is row 1)
            try:
                # Normalize row keys to lowercase
                normalized_row = {k.lower().strip(): v for k, v in row.items()}
                
                # Parse date with multiple formats
                date_str = normalized_row.get(date_col, '').strip()
                if not date_str:
                    parse_errors.append(f"Row {row_num}: Missing date value")
                    continue
                
                parsed_date = None
                for date_format in ['%Y-%m-%d', '%Y/%m/%d', '%d-%m-%Y', '%d/%m/%Y', '%m/%d/%Y', '%Y%m%d']:
                    try:
                        parsed_date = datetime.strptime(date_str, date_format)
                        break
                    except ValueError:
                        continue
                
                if not parsed_date:
                    parse_errors.append(f"Row {row_num}: Invalid date format '{date_str}'")
                    continue
                
                # Parse revenue
                revenue_str = normalized_row.get(revenue_col, '').strip()
                if not revenue_str:
                    parse_errors.append(f"Row {row_num}: Missing revenue value")
                    continue
                
                # Remove currency symbols and commas
                revenue_str = revenue_str.replace('$', '').replace('€', '').replace('£', '').replace(',', '').strip()
                
                try:
                    revenue = float(revenue_str)
                except ValueError:
                    parse_errors.append(f"Row {row_num}: Invalid revenue value '{revenue_str}'")
                    continue
                
                if revenue < 0:
                    parse_errors.append(f"Row {row_num}: Revenue cannot be negative")
                    continue
                
                # Parse orders (optional)
                orders = 1
                if orders_col:
                    orders_str = normalized_row.get(orders_col, '1').strip()
                    try:
                        orders = int(orders_str)
                    except ValueError:
                        orders = 1
                
                data.append({
                    'date': parsed_date,
                    'revenue': revenue,
                    'orders': orders
                })
            except Exception as e:
                parse_errors.append(f"Row {row_num}: {str(e)}")
                continue
        
        if not data:
            error_msg = "No valid data found in CSV"
            if parse_errors:
                error_msg += f". First few errors: {parse_errors[:5]}"
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Sort by date
        data.sort(key=lambda x: x['date'])
        
        # Check for duplicate dates and aggregate
        date_dict = {}
        for item in data:
            date_str = item['date'].strftime('%Y-%m-%d')
            if date_str in date_dict:
                date_dict[date_str]['revenue'] += item['revenue']
                date_dict[date_str]['orders'] += item['orders']
            else:
                date_dict[date_str] = {
                    'date': date_str,
                    'revenue': item['revenue'],
                    'orders': item['orders']
                }
        
        # Convert back to list
        data = list(date_dict.values())
        data.sort(key=lambda x: x['date'])
        
        # Return response with warnings if there were parse errors
        response_data = {
            "success": True,
            "message": f"Successfully loaded {len(data)} records",
            "data": data,
            "record_count": len(data),
            "columns_found": {
                "date": date_col,
                "revenue": revenue_col,
                "orders": orders_col
            }
        }
        
        if parse_errors:
            response_data["warnings"] = f"Some rows had errors and were skipped: {len(parse_errors)} errors"
            response_data["sample_errors"] = parse_errors[:3]
        
        return JSONResponse(response_data)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_detail = f"Error processing CSV: {str(e)}"
        logger.error(f"CSV upload error: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=error_detail)


@router.post("/api/admin/forecast/with-custom-data")
def forecast_with_custom_data(
    request: Request,
    body: dict = Body(...),
    db: Session = Depends(get_db)
):
    """Generate forecast using custom uploaded data"""
    try:
        user = get_current_user(request, db)
        if not user or not user.is_admin:
            return JSONResponse({"error": "Admin access required"}, status_code=403)
        
        # Parse date strings to datetime objects
        raw_data = body.get('data', [])
        model_type = body.get('model_type', 'all')
        periods = body.get('periods', 30)
        
        parsed_data = []
        for item in raw_data:
            try:
                parsed_data.append({
                    'date': datetime.strptime(item['date'], '%Y-%m-%d'),
                    'revenue': float(item['revenue']),
                    'orders': int(item.get('orders', 1))
                })
            except (ValueError, KeyError) as e:
                print(f"Error parsing row: {item}, error: {e}")
                continue
        
        if not parsed_data:
            return JSONResponse({"error": "No valid data after parsing"}, status_code=400)
        
        result = demand_forecasting_service.train_and_forecast(
            db=db,
            model_type=model_type,
            periods=periods,
            custom_data=parsed_data
        )
        return JSONResponse(result)
    except Exception as e:
        import traceback
        error_msg = f"Forecast error: {str(e)}"
        print(error_msg)
        print(traceback.format_exc())
        return JSONResponse({"error": error_msg, "traceback": traceback.format_exc()}, status_code=500)

@router.get("/api/admin/anomaly/detect")
def detect_anomalies(request: Request, db: Session = Depends(get_db)):
    """Detect anomalies using ML models"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    report = anomaly_detection_service.get_comprehensive_anomaly_report(db)
    return JSONResponse(report)


@router.get("/api/admin/anomaly/heatmap")
def get_anomaly_heatmap(request: Request, db: Session = Depends(get_db)):
    """Get anomaly heatmap data"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    heatmap = anomaly_detection_service.get_anomaly_heatmap_data(db)
    return JSONResponse({"heatmap": heatmap})


@router.get("/api/admin/anomaly/metrics")
def get_fraud_metrics(request: Request, db: Session = Depends(get_db)):
    """Get fraud detection metrics"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    metrics = anomaly_detection_service.get_fraud_metrics(db)
    return JSONResponse(metrics)


@router.post("/api/admin/anomaly/{order_id}/mark-fraud")
def mark_order_fraud(order_id: int, request: Request, db: Session = Depends(get_db)):
    """Mark an order as fraudulent"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    success = anomaly_detection_service.mark_as_fraud(order_id, db)
    return JSONResponse({"success": success})


@router.get("/admin/anomaly", response_class=HTMLResponse)
def anomaly_dashboard(request: Request, db: Session = Depends(get_db)):
    """Anomaly detection dashboard page"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    return templates.TemplateResponse(
        "anomaly_dashboard.html",
        {
            "request": request,
            "user": user,
            "current_product_id": None,
        },
    )


@router.get("/api/admin/agents/status")
def get_agents_status(request: Request, db: Session = Depends(get_db)):
    """Get status of all agents"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    status = ai_multi_agent_center.get_agent_status()
    return JSONResponse(status)


@router.post("/api/admin/agents/{agent_name}/execute")
def execute_agent_task(agent_name: str, request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Execute a task through a specific agent"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    task_type = payload.get("task_type")
    params = payload.get("params", {})
    
    result = ai_multi_agent_center.execute_task(agent_name, task_type, params, db)
    return JSONResponse(result)


@router.get("/api/admin/agents/tasks")
def get_agent_tasks(request: Request, limit: int = 50, db: Session = Depends(get_db)):
    """Get agent task history"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    tasks = ai_multi_agent_center.get_task_history(limit)
    return JSONResponse({"tasks": tasks})


@router.get("/api/admin/agents/logs")
def get_agent_logs(request: Request, limit: int = 100, db: Session = Depends(get_db)):
    """Get orchestration logs"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    logs = ai_multi_agent_center.get_orchestration_logs(limit)
    return JSONResponse({"logs": logs})


@router.post("/api/admin/agents/{agent_name}/reset")
def reset_agent(agent_name: str, request: Request, db: Session = Depends(get_db)):
    """Reset an agent"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    success = ai_multi_agent_center.reset_agent(agent_name)
    return JSONResponse({"success": success})


@router.get("/api/admin/inventory/predict-shortages")
def predict_inventory_shortages(request: Request, days_ahead: int = 14, db: Session = Depends(get_db)):
    """Predict inventory shortages using Inventory Agent"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    result = ai_multi_agent_center.execute_task("inventory", "predict_shortages", {"days_ahead": days_ahead}, db)
    return JSONResponse(result)


@router.get("/api/admin/inventory/recommend-reorder")
def recommend_reorder_quantities(request: Request, product_id: int = None, db: Session = Depends(get_db)):
    """Get reorder recommendations from Inventory Agent"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    result = ai_multi_agent_center.execute_task("inventory", "recommend_reorder", {"product_id": product_id}, db)
    return JSONResponse(result)


@router.get("/api/admin/inventory/anomalies")
def detect_inventory_anomalies(request: Request, db: Session = Depends(get_db)):
    """Detect inventory anomalies using Inventory Agent"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    result = ai_multi_agent_center.execute_task("inventory", "detect_anomalies", {}, db)
    return JSONResponse(result)


@router.get("/api/admin/inventory/warehouse-analytics")
def get_warehouse_analytics(request: Request, db: Session = Depends(get_db)):
    """Get warehouse analytics from Inventory Agent"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    result = ai_multi_agent_center.execute_task("inventory", "warehouse_analytics", {}, db)
    return JSONResponse(result)


@router.get("/admin/agents", response_class=HTMLResponse)
def agents_control_center(request: Request, db: Session = Depends(get_db)):
    """Multi-Agent Control Center page"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    return templates.TemplateResponse(
        "agents_control_center.html",
        {
            "request": request,
            "user": user,
            "current_product_id": None,
        },
    )


@router.get("/api/admin/agents/communications")
def get_agent_communications(request: Request, limit: int = 50, db: Session = Depends(get_db)):
    """Get inter-agent communications (MCP protocol logs)"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    comms = ai_multi_agent_center.get_agent_communications(limit)
    return JSONResponse({"communications": comms})


@router.post("/api/admin/agents/orchestrate")
def orchestrate_multi_agent(request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Orchestrate a complex task across multiple agents"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    task_plan = payload.get("task_plan", [])
    if not task_plan:
        raise HTTPException(status_code=400, detail="Task plan required")
    
    result = ai_multi_agent_center.orchestrate_multi_agent_task(task_plan, db)
    return JSONResponse(result)


@router.post("/api/admin/agents/{agent_name}/ai-analysis")
def agent_ai_analysis(agent_name: str, request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Execute AI-powered analysis task on an agent"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    task_type_mapping = {
        "inventory": "ai_inventory_analysis",
        "retail_analyst": "ai_retail_insights",
        "ml_insights": "ai_ml_analysis",
        "document_intelligence": "semantic_search"
    }
    
    ai_task_type = task_type_mapping.get(agent_name)
    if not ai_task_type:
        raise HTTPException(status_code=400, detail=f"AI analysis not available for agent: {agent_name}")
    
    result = ai_multi_agent_center.execute_task(agent_name, ai_task_type, payload, db)
    return JSONResponse(result)


@router.post("/api/admin/agents/document/answer")
def document_answer_question(request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Answer question using Document Intelligence Agent with RAG"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    question = payload.get("question")
    if not question:
        raise HTTPException(status_code=400, detail="Question required")
    
    result = ai_multi_agent_center.execute_task(
        "document_intelligence",
        "answer_question",
        {"question": question},
        db
    )
    return JSONResponse(result)


@router.get("/admin/inventory/ai", response_class=HTMLResponse)
def inventory_ai_dashboard(request: Request, db: Session = Depends(get_db)):
    """AI Inventory Management Dashboard"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    return templates.TemplateResponse(
        "inventory_ai_dashboard.html",
        {
            "request": request,
            "user": user,
            "current_product_id": None,
        },
    )


# ───────────────────────────────────────────────────────────────────────────────
# STORE MANAGEMENT ROUTES
# ───────────────────────────────────────────────────────────────────────────────

@router.get("/admin/products", response_class=HTMLResponse)
def admin_products(request: Request, db: Session = Depends(get_db)):
    """Products Management Page"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    # Get all products
    products = db.query(Product).order_by(Product.created_at.desc()).all()
    
    # Get product statistics
    total_products = len(products)
    low_stock_count = len([p for p in products if p.stock < 10])
    out_of_stock_count = len([p for p in products if p.stock == 0])
    total_value = sum(p.price * p.stock for p in products)
    
    # Get categories
    categories = db.query(Product.category).distinct().all()
    categories = [c[0] for c in categories]
    
    return templates.TemplateResponse(
        "admin_products.html",
        {
            "request": request,
            "user": user,
            "products": products,
            "total_products": total_products,
            "low_stock_count": low_stock_count,
            "out_of_stock_count": out_of_stock_count,
            "total_value": total_value,
            "categories": categories,
            "current_product_id": None,
        },
    )


@router.get("/api/admin/products")
def api_get_products(
    request: Request,
    category: str = None,
    search: str = None,
    stock_status: str = None,
    db: Session = Depends(get_db)
):
    """API to get products with filters"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    query = db.query(Product)
    
    if category:
        query = query.filter(Product.category == category)
    
    if search:
        search = f"%{search}%"
        query = query.filter(
            (Product.name.ilike(search)) | (Product.sku.ilike(search))
        )
    
    if stock_status:
        if stock_status == "low":
            query = query.filter(Product.stock < 10)
        elif stock_status == "out":
            query = query.filter(Product.stock == 0)
        elif stock_status == "in":
            query = query.filter(Product.stock > 0)
    
    products = query.order_by(Product.created_at.desc()).all()
    
    return JSONResponse([{
        "id": p.id,
        "sku": p.sku,
        "name": p.name,
        "category": p.category,
        "price": p.price,
        "stock": p.stock,
        "image": p.image,
        "sizes": p.sizes,
        "created_at": p.created_at.isoformat() if p.created_at else None
    } for p in products])


@router.get("/api/admin/products/{product_id}")
def api_get_product(product_id: int, request: Request, db: Session = Depends(get_db)):
    """API to get a single product by ID"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    return JSONResponse({
        "id": product.id,
        "sku": product.sku,
        "name": product.name,
        "category": product.category,
        "description": product.description,
        "price": product.price,
        "stock": product.stock,
        "image": product.image,
        "sizes": product.sizes,
        "created_at": product.created_at.isoformat() if product.created_at else None
    })


@router.post("/api/admin/products")
def api_create_product(
    request: Request,
    sku: str = Form(...),
    name: str = Form(...),
    category: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    stock: int = Form(...),
    sizes: str = Form("S,M,L,XL"),
    db: Session = Depends(get_db)
):
    """API to create a new product"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # Check if SKU exists
    existing = db.query(Product).filter(Product.sku == sku).first()
    if existing:
        raise HTTPException(status_code=400, detail="SKU already exists")
    
    product = Product(
        sku=sku,
        name=name,
        category=category,
        description=description,
        price=price,
        stock=stock,
        sizes=sizes,
        image="/static/images/default-product.jpg"
    )
    db.add(product)
    db.commit()
    db.refresh(product)
    
    return JSONResponse({
        "success": True,
        "message": "Product created successfully",
        "product_id": product.id
    })


@router.put("/api/admin/products/{product_id}")
def api_update_product(
    product_id: int,
    request: Request,
    name: str = Form(None),
    category: str = Form(None),
    description: str = Form(None),
    price: float = Form(None),
    stock: int = Form(None),
    sizes: str = Form(None),
    db: Session = Depends(get_db)
):
    """API to update a product"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    if name:
        product.name = name
    if category:
        product.category = category
    if description:
        product.description = description
    if price is not None:
        product.price = price
    if stock is not None:
        product.stock = stock
    if sizes:
        product.sizes = sizes
    
    db.commit()
    db.refresh(product)
    
    return JSONResponse({
        "success": True,
        "message": "Product updated successfully"
    })


@router.delete("/api/admin/products/{product_id}")
def api_delete_product(product_id: int, request: Request, db: Session = Depends(get_db)):
    """API to delete a product"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    db.delete(product)
    db.commit()
    
    return JSONResponse({
        "success": True,
        "message": "Product deleted successfully"
    })


@router.get("/admin/inventory", response_class=HTMLResponse)
def admin_inventory(request: Request, db: Session = Depends(get_db)):
    """Inventory Management Page"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    # Get inventory data
    products = db.query(Product).order_by(Product.stock.asc()).all()
    
    # Calculate metrics
    total_products = len(products)
    low_stock = len([p for p in products if 0 < p.stock < 10])
    out_of_stock = len([p for p in products if p.stock == 0])
    healthy_stock = len([p for p in products if p.stock >= 10])
    
    # Calculate inventory value by category
    category_values = {}
    for p in products:
        if p.category not in category_values:
            category_values[p.category] = 0
        category_values[p.category] += p.price * p.stock
    
    return templates.TemplateResponse(
        "admin_inventory.html",
        {
            "request": request,
            "user": user,
            "products": products,
            "total_products": total_products,
            "low_stock": low_stock,
            "out_of_stock": out_of_stock,
            "healthy_stock": healthy_stock,
            "category_values": category_values,
            "current_product_id": None,
        },
    )


@router.post("/api/admin/inventory/update/{product_id}")
def api_update_inventory(
    product_id: int,
    request: Request,
    stock_change: int = Form(...),
    reason: str = Form(""),
    db: Session = Depends(get_db)
):
    """API to update product inventory"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    new_stock = product.stock + stock_change
    if new_stock < 0:
        raise HTTPException(status_code=400, detail="Stock cannot be negative")
    
    product.stock = new_stock
    db.commit()
    
    return JSONResponse({
        "success": True,
        "message": "Inventory updated",
        "new_stock": new_stock,
        "product_name": product.name
    })


@router.get("/admin/orders", response_class=HTMLResponse)
def admin_orders(
    request: Request,
    status: str = None,
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db)
):
    """Orders Management Page"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    # Build query and eager load order items
    query = db.query(Order).options(selectinload(Order.items))
    
    if status:
        query = query.filter(Order.status == status)
    
    if date_from:
        try:
            from datetime import datetime
            from_date = datetime.strptime(date_from, "%Y-%m-%d")
            query = query.filter(Order.created_at >= from_date)
        except:
            pass
    
    if date_to:
        try:
            from datetime import datetime
            to_date = datetime.strptime(date_to, "%Y-%m-%d")
            query = query.filter(Order.created_at <= to_date)
        except:
            pass
    
    orders = query.order_by(Order.created_at.desc()).all()
    
    # Calculate statistics
    total_orders = len(orders)
    total_revenue = sum(o.total_amount for o in orders)
    pending_orders = len([o for o in orders if o.status == "Processing"])
    shipped_orders = len([o for o in orders if o.status == "Shipped"])
    delivered_orders = len([o for o in orders if o.status == "Delivered"])
    cancelled_orders = len([o for o in orders if o.status == "Cancelled"])
    
    return templates.TemplateResponse(
        "admin_orders.html",
        {
            "request": request,
            "user": user,
            "orders": orders,
            "total_orders": total_orders,
            "total_revenue": total_revenue,
            "pending_orders": pending_orders,
            "shipped_orders": shipped_orders,
            "delivered_orders": delivered_orders,
            "cancelled_orders": cancelled_orders,
            "current_filter": status,
            "current_product_id": None,
        },
    )


@router.get("/api/admin/orders/{order_id}")
def api_get_order_details(order_id: int, request: Request, db: Session = Depends(get_db)):
    """API to get order details"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    order = db.query(Order).filter(Order.id == order_id).options(selectinload(Order.items)).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    return JSONResponse({
        "id": order.id,
        "order_number": order.order_number,
        "customer_name": order.customer_name,
        "phone": order.phone,
        "address": order.address,
        "city": order.city,
        "state": order.state,
        "pincode": order.pincode,
        "status": order.status,
        "tracking_id": order.tracking_id,
        "total_amount": order.total_amount,
        "payment_method": order.payment_method,
        "payment_status": order.payment_status,
        "return_status": order.return_status,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "items": [{
            "product_name": item.product_name,
            "size": item.size,
            "quantity": item.quantity,
            "unit_price": item.unit_price
        } for item in order.items]
    })


@router.post("/api/admin/orders/{order_id}/status")
def api_update_order_status(
    order_id: int,
    request: Request,
    status: str = Form(...),
    tracking_id: str = Form(None),
    db: Session = Depends(get_db)
):
    """API to update order status"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    valid_statuses = ["Processing", "Shipped", "Delivered", "Cancelled", "Returned"]
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    order.status = status
    if tracking_id:
        order.tracking_id = tracking_id
    
    db.commit()
    
    return JSONResponse({
        "success": True,
        "message": f"Order status updated to {status}"
    })


@router.get("/admin/payments", response_class=HTMLResponse)
def admin_payments(request: Request, db: Session = Depends(get_db)):
    """Payments Management Page"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    orders = db.query(Order).order_by(Order.created_at.desc()).all()
    
    # Calculate payment statistics
    total_revenue = sum(o.total_amount for o in orders if o.payment_status == "Completed")
    pending_amount = sum(o.total_amount for o in orders if o.payment_status == "Pending")
    cod_orders = len([o for o in orders if o.payment_method == "COD"])
    online_orders = len([o for o in orders if o.payment_method != "COD"])
    
    # Payment method breakdown
    method_totals = {}
    for o in orders:
        method = o.payment_method
        if method not in method_totals:
            method_totals[method] = {"count": 0, "amount": 0}
        method_totals[method]["count"] += 1
        if o.payment_status == "Completed":
            method_totals[method]["amount"] += o.total_amount
    
    return templates.TemplateResponse(
        "admin_payments.html",
        {
            "request": request,
            "user": user,
            "orders": orders,
            "total_revenue": total_revenue,
            "pending_amount": pending_amount,
            "cod_orders": cod_orders,
            "online_orders": online_orders,
            "method_totals": method_totals,
            "current_product_id": None,
        },
    )


@router.post("/api/admin/payments/{order_id}/verify")
def api_verify_payment(
    order_id: int,
    request: Request,
    payment_reference: str = Form(...),
    db: Session = Depends(get_db)
):
    """API to verify payment"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order.payment_status = "Completed"
    order.payment_reference = payment_reference
    db.commit()
    
    return JSONResponse({
        "success": True,
        "message": "Payment verified successfully"
    })


@router.get("/admin/shipping", response_class=HTMLResponse)
def admin_shipping(request: Request, db: Session = Depends(get_db)):
    """Shipping Management Page"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    # Get orders that need shipping
    orders = db.query(Order).filter(
        Order.status.in_(["Processing", "Shipped", "Delivered"])
    ).order_by(Order.created_at.desc()).all()
    
    # Calculate statistics
    to_ship = len([o for o in orders if o.status == "Processing"])
    in_transit = len([o for o in orders if o.status == "Shipped"])
    delivered = len([o for o in orders if o.status == "Delivered"])
    
    return templates.TemplateResponse(
        "admin_shipping.html",
        {
            "request": request,
            "user": user,
            "orders": orders,
            "to_ship": to_ship,
            "in_transit": in_transit,
            "delivered": delivered,
            "current_product_id": None,
        },
    )


@router.post("/api/admin/shipping/{order_id}/ship")
def api_ship_order(
    order_id: int,
    request: Request,
    tracking_id: str = Form(...),
    carrier: str = Form("Standard"),
    db: Session = Depends(get_db)
):
    """API to mark order as shipped"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    order.status = "Shipped"
    order.tracking_id = tracking_id
    db.commit()
    
    return JSONResponse({
        "success": True,
        "message": "Order marked as shipped",
        "tracking_id": tracking_id
    })


@router.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)

    products = db.query(Product).order_by(Product.id.desc()).all()
    orders = db.query(Order).order_by(Order.created_at.desc()).limit(12).all()
    tickets = db.query(SupportTicket).order_by(SupportTicket.created_at.desc()).limit(20).all()

    metrics = mongo_service.get_dashboard_metrics()
    if tickets:
        metrics["tickets"] = max(metrics.get("tickets", 0), len(tickets))

    revenue = (
        db.query(func.coalesce(func.sum(Order.total_amount), 0.0))
        .filter(Order.payment_status.in_(["Paid", "Pending"]))
        .scalar()
        or 0.0
    )
    total_orders = db.query(func.count(Order.id)).scalar() or 0

    return templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request,
            "user": user,
            "products": products,
            "orders": orders,
            "tickets": tickets,
            "metrics": metrics,
            "revenue": revenue,
            "total_orders": total_orders,
            "admin_email": settings.admin_email,
            "admin_password": settings.admin_password,
            "current_product_id": None,
        },
    )


@router.post("/admin/product/add")
def add_product(
    request: Request,
    sku: str = Form(...),
    name: str = Form(...),
    category: str = Form(...),
    description: str = Form(...),
    price: float = Form(...),
    stock: int = Form(...),
    image: str = Form(...),
    sizes: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)

    db.add(
        Product(
            sku=sku,
            name=name,
            category=category,
            description=description,
            price=price,
            stock=stock,
            image=image,
            sizes=sizes,
        )
    )
    db.commit()
    return RedirectResponse(url="/admin", status_code=302)


@router.post("/admin/product/{product_id}/edit")
def edit_product(
    request: Request,
    product_id: int,
    price: float = Form(...),
    stock: int = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)

    product = db.query(Product).filter(Product.id == product_id).first()
    if product:
        product.price = price
        product.stock = stock
        db.commit()

    return RedirectResponse(url="/admin", status_code=302)


@router.post("/admin/order/{order_id}/status")
def update_order_status(request: Request, order_id: int, status: str = Form(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)

    order = db.query(Order).filter(Order.id == order_id).first()
    if order:
        order.status = status
        if status == "Delivered" and order.payment_method == "COD":
            order.payment_status = "Paid"
        db.commit()

    return RedirectResponse(url="/admin", status_code=302)

@router.post("/admin/order/{order_id}/approve-return")
def approve_return(request: Request, order_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.return_status == "Return Requested":
        order.return_status = "Return Approved"
        db.commit()

    return RedirectResponse(url="/admin", status_code=302)

@router.post("/admin/order/{order_id}/complete-return")
def complete_return(request: Request, order_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.return_status == "Return Approved":
        order.return_status = "Returned"
        order.status = "Returned"
        if order.payment_method == "Online" and order.payment_status == "Paid":
            order.payment_status = "Refunded"
        db.commit()

    return RedirectResponse(url="/admin", status_code=302)

@router.post("/admin/ticket/{ticket_id}/status")
def update_ticket_status(
    request: Request,
    ticket_id: int,
    status: str = Form(...),
    admin_note: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)

    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if ticket:
        ticket.status = status
        ticket.admin_note = admin_note
        db.commit()
        mongo_service.update_ticket_status(ticket.ticket_number, status, admin_note)

    return RedirectResponse(url="/admin", status_code=302)


@router.post("/admin/upload-kb")
def upload_knowledge_file(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)

    content = file.file.read().decode("utf-8", errors="ignore")
    file_path = KB_DIR / file.filename.replace(" ", "_")
    file_path.write_text(content, encoding="utf-8")
    rag_service.ingest_knowledge_files()

    return RedirectResponse(url="/admin", status_code=302)


# ==================== USER MANAGEMENT API ====================

@router.get("/api/admin/users")
def get_all_users(request: Request, db: Session = Depends(get_db)):
    """Get all users with roles and activity"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    users = user_management_service.get_all_users_with_roles(db)
    total_spent = db.query(func.sum(Order.total_amount)).scalar() or 0
    return JSONResponse({"users": users, "total_spent": float(total_spent)})


@router.get("/api/admin/users/{user_id}/activity")
def get_user_activity_admin(user_id: int, request: Request, days: int = 30, db: Session = Depends(get_db)):
    """Get detailed user activity for admin"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    activity = user_management_service.get_user_activity(db, user_id, days)
    return JSONResponse(activity)


@router.get("/api/admin/users/suspicious")
def get_suspicious_users(request: Request, db: Session = Depends(get_db)):
    """Detect suspicious user behavior"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    suspicious = user_management_service.detect_suspicious_users(db)
    return JSONResponse({"suspicious_users": suspicious})


@router.get("/api/admin/audit-logs")
def get_audit_logs(request: Request, user_id: int = None, entity_type: str = None, 
                   limit: int = 100, db: Session = Depends(get_db)):
    """Get audit logs"""
    admin = get_current_user(request, db)
    if not admin or not admin.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    logs = user_management_service.get_audit_logs(db, user_id, entity_type, limit)
    return JSONResponse({"logs": logs})


# ==================== DOCUMENT INTELLIGENCE API ====================

@router.post("/api/admin/documents/upload")
async def upload_admin_document(
    request: Request,
    file: UploadFile = File(...),
    document_type: str = Form(...),
    db: Session = Depends(get_db)
):
    """Upload document for processing"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    file_data = await file.read()
    
    result = document_intelligence_service.store_document(
        db, file_data, file.filename, document_type, user.id, file.content_type
    )
    
    return JSONResponse(result)


@router.post("/api/admin/documents/{document_id}/process")
def process_document(document_id: str, request: Request, db: Session = Depends(get_db)):
    """Process document with OCR"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # Perform OCR
    ocr_result = document_intelligence_service.perform_ocr(db, document_id)
    
    # Index document
    if ocr_result.get("status") == "processed":
        index_result = document_intelligence_service.index_document(db, document_id)
        return JSONResponse({"ocr": ocr_result, "indexing": index_result})
    
    return JSONResponse(ocr_result)


@router.get("/api/admin/documents")
def list_admin_documents(request: Request, document_type: str = None, 
                        status: str = None, limit: int = 50, db: Session = Depends(get_db)):
    """List all admin documents"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    docs = document_intelligence_service.list_documents(db, document_type, status, limit)
    return JSONResponse({"documents": docs})


@router.get("/api/admin/documents/{document_id}")
def get_admin_document(document_id: str, request: Request, db: Session = Depends(get_db)):
    """Get document details"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    doc = document_intelligence_service.get_document(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    return JSONResponse(doc)


@router.get("/api/admin/documents/search")
def search_admin_documents(request: Request, query: str, document_type: str = None,
                          limit: int = 10, db: Session = Depends(get_db)):
    """Search documents"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    results = document_intelligence_service.search_documents(db, query, document_type, limit)
    return JSONResponse({"results": results})


@router.delete("/api/admin/documents/{document_id}")
def delete_admin_document(document_id: str, request: Request, db: Session = Depends(get_db)):
    """Delete a document"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    success = document_intelligence_service.delete_document(db, document_id)
    return JSONResponse({"success": success})


@router.get("/api/admin/documents/types")
def get_document_types(request: Request, db: Session = Depends(get_db)):
    """Get available document types"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    types = document_intelligence_service.get_document_types()
    return JSONResponse({"types": types})


# ==================== ADMIN PAGES ====================

@router.get("/admin/users", response_class=HTMLResponse)
def admin_user_management(request: Request, db: Session = Depends(get_db)):
    """User Management page"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    return templates.TemplateResponse(
        "admin_user_management.html",
        {
            "request": request,
            "user": user,
            "current_product_id": None,
        },
    )


@router.get("/admin/documents", response_class=HTMLResponse)
def admin_document_intelligence(request: Request, db: Session = Depends(get_db)):
    """Document Intelligence Panel"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    return templates.TemplateResponse(
        "admin_document_intelligence.html",
        {
            "request": request,
            "user": user,
            "current_product_id": None,
        },
    )


# ==================== AZURE MANAGEMENT API ====================

@router.get("/api/admin/azure/status")
def get_azure_service_status(request: Request, db: Session = Depends(get_db)):
    """Get Azure service status"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    status = azure_management_service.get_service_status()
    return JSONResponse(status)


@router.get("/api/admin/azure/metrics")
def get_azure_service_metrics(request: Request, service_id: str = None, db: Session = Depends(get_db)):
    """Get Azure service metrics"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    metrics = azure_management_service.get_service_metrics(service_id)
    return JSONResponse(metrics)


@router.get("/api/admin/azure/deployment-logs")
def get_deployment_logs(request: Request, limit: int = 50, db: Session = Depends(get_db)):
    """Get deployment logs"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    logs = azure_management_service.get_deployment_logs(limit)
    return JSONResponse({"logs": logs})


@router.get("/api/admin/azure/model-endpoints")
def get_model_endpoints(request: Request, db: Session = Depends(get_db)):
    """Get ML model endpoints"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    endpoints = azure_management_service.get_model_endpoints()
    return JSONResponse({"endpoints": endpoints})


@router.get("/api/admin/azure/storage")
def get_storage_usage(request: Request, db: Session = Depends(get_db)):
    """Get storage usage"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    storage = azure_management_service.get_storage_usage()
    return JSONResponse(storage)


@router.get("/api/admin/azure/costs")
def get_azure_costs(request: Request, db: Session = Depends(get_db)):
    """Get Azure cost summary"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    costs = azure_management_service.get_cost_summary()
    return JSONResponse(costs)


# ==================== DATA ENGINEERING API ====================

@router.get("/api/admin/data/pipelines")
def get_pipeline_status(request: Request, db: Session = Depends(get_db)):
    """Get data pipeline status"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    status = data_engineering_service.get_pipeline_status()
    return JSONResponse(status)


@router.get("/api/admin/data/pipelines/{pipeline_id}/runs")
def get_pipeline_runs(pipeline_id: str, request: Request, limit: int = 50, db: Session = Depends(get_db)):
    """Get pipeline run history"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    runs = data_engineering_service.get_pipeline_runs(pipeline_id, limit)
    return JSONResponse({"runs": runs})


@router.get("/api/admin/data/flow")
def get_data_flow_status(request: Request, db: Session = Depends(get_db)):
    """Get data flow status"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    flow = data_engineering_service.get_data_flow_status()
    return JSONResponse(flow)


@router.get("/api/admin/data/ingestion")
def get_ingestion_jobs(request: Request, db: Session = Depends(get_db)):
    """Get ingestion jobs"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    jobs = data_engineering_service.get_ingestion_jobs()
    return JSONResponse({"jobs": jobs})


@router.get("/api/admin/data/databricks")
def get_databricks_runs(request: Request, db: Session = Depends(get_db)):
    """Get Databricks job runs"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    runs = data_engineering_service.get_databricks_runs()
    return JSONResponse({"runs": runs})


@router.get("/api/admin/data/adf")
def get_adf_pipelines(request: Request, db: Session = Depends(get_db)):
    """Get Azure Data Factory pipelines"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    pipelines = data_engineering_service.get_adf_pipelines()
    return JSONResponse({"pipelines": pipelines})


@router.get("/api/admin/data/statistics")
def get_job_statistics(request: Request, db: Session = Depends(get_db)):
    """Get job statistics"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    stats = data_engineering_service.get_job_statistics()
    return JSONResponse(stats)


@router.get("/api/admin/database/tables")
def get_database_tables(request: Request, db: Session = Depends(get_db)):
    """Get list of database tables"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    from sqlalchemy import inspect, text
    inspector = inspect(db.bind)
    tables = []
    for table_name in inspector.get_table_names():
        columns = inspector.get_columns(table_name)
        row_count = db.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
        tables.append({
            "name": table_name,
            "columns": [{"name": c["name"], "type": str(c["type"])} for c in columns],
            "row_count": row_count
        })
    return JSONResponse({"tables": tables})


@router.get("/api/admin/database/tables/{table_name}/data")
def get_table_data(table_name: str, limit: int = 100, offset: int = 0, request: Request = None, db: Session = Depends(get_db)):
    """Get data from a specific table"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    from sqlalchemy import inspect, text
    inspector = inspect(db.bind)
    table_names = inspector.get_table_names()

    if table_name not in table_names:
        raise HTTPException(status_code=404, detail="Table not found")

    columns = [c["name"] for c in inspector.get_columns(table_name)]

    # Get total count
    total = db.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar()

    # Get data
    rows = db.execute(text(f"SELECT * FROM {table_name} LIMIT :limit OFFSET :offset"),
                     {"limit": limit, "offset": offset}).fetchall()

    data = []
    for row in rows:
        row_dict = {}
        for i, col in enumerate(columns):
            val = row[i]
            # Convert non-serializable types
            if hasattr(val, 'isoformat'):
                row_dict[col] = val.isoformat()
            else:
                row_dict[col] = val
        data.append(row_dict)

    return JSONResponse({
        "columns": columns,
        "data": data,
        "total": total,
        "limit": limit,
        "offset": offset
    })


# ==================== ADMIN PAGES ====================

@router.get("/admin/azure", response_class=HTMLResponse)
def admin_azure_management(request: Request, db: Session = Depends(get_db)):
    """Azure Management Panel"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    return templates.TemplateResponse(
        "admin_azure_management.html",
        {
            "request": request,
            "user": user,
            "current_product_id": None,
        },
    )


@router.get("/admin/data")
def admin_data_engineering_redirect(request: Request, db: Session = Depends(get_db)):
    """Redirect old Data Engineering page to new Data Pipeline page"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    return RedirectResponse(url="/admin/data-pipeline", status_code=302)


# ==================== POWER BI ANALYTICS API ====================

def _money(value: float) -> str:
    return f"Rs {float(value or 0):,.0f}"


def _moving_average(values: list[float], window: int = 7) -> float:
    values = [float(v or 0) for v in values]
    if not values:
        return 0.0
    sample = values[-window:] if len(values) >= window else values
    return sum(sample) / len(sample)


def _build_powerbi_visuals(dashboard_id: str, db: Session) -> dict:
    analytics = admin_analytics_service.get_comprehensive_dashboard(db)
    metrics = analytics["metrics"]
    revenue_trends = analytics["revenue_trends"]
    inventory_trends = analytics["inventory_trends"]
    top_products = analytics["top_selling_products"]
    low_stock = analytics["low_stock_alerts"]
    status_breakdown = analytics["order_status_breakdown"]

    if dashboard_id == "sales_analytics":
        return {
            "cards": [
                {"label": "Revenue", "value": _money(metrics["total_revenue"]), "hint": "All recorded orders"},
                {"label": "Orders", "value": metrics["total_orders"], "hint": f"Today: {metrics['today_orders']}"},
                {"label": "Average Order", "value": _money(metrics["avg_order_value"]), "hint": "Revenue per order"},
                {"label": "Profit", "value": _money(metrics["profit"]), "hint": "Estimated at 20% margin"},
            ],
            "charts": [
                {
                    "title": "Revenue and Orders Trend",
                    "type": "line",
                    "labels": [r["date"] for r in revenue_trends],
                    "datasets": [
                        {"label": "Revenue", "data": [r["revenue"] for r in revenue_trends], "borderColor": "#2563eb", "backgroundColor": "rgba(37,99,235,.12)", "yAxisID": "y"},
                        {"label": "Orders", "data": [r["orders"] for r in revenue_trends], "borderColor": "#10b981", "backgroundColor": "rgba(16,185,129,.12)", "yAxisID": "y1"},
                    ],
                },
                {
                    "title": "Top Selling Products",
                    "type": "bar",
                    "labels": [p["name"] for p in top_products[:8]],
                    "datasets": [
                        {"label": "Units Sold", "data": [p["total_sold"] for p in top_products[:8]], "backgroundColor": "#7c3aed"},
                    ],
                },
                {
                    "title": "Order Status Mix",
                    "type": "doughnut",
                    "labels": list(status_breakdown.keys()),
                    "datasets": [
                        {"label": "Orders", "data": list(status_breakdown.values()), "backgroundColor": ["#2563eb", "#06b6d4", "#8b5cf6", "#f59e0b", "#10b981", "#ef4444", "#64748b"]},
                    ],
                },
            ],
            "tables": [
                {
                    "title": "Product Revenue Leaders",
                    "headers": ["Product", "Category", "Sold", "Revenue"],
                    "rows": [[p["name"], p["category"], p["total_sold"], _money(p["total_revenue"])] for p in top_products[:10]],
                }
            ],
            "insights": analytics["ai_insights"] or ["Sales data is available. Add more orders to unlock richer trend insights."],
        }

    if dashboard_id == "forecasting":
        historical = [r["revenue"] for r in revenue_trends]
        avg = _moving_average(historical)
        forecast_labels = [(datetime.utcnow() + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, 15)]
        forecast_values = [round(avg * (1 + (i % 5 - 2) * 0.025), 2) for i in range(1, 15)]
        labels = [r["date"] for r in revenue_trends] + forecast_labels
        historical_series = historical + [None] * len(forecast_labels)
        forecast_series = [None] * len(revenue_trends) + forecast_values
        return {
            "cards": [
                {"label": "Next 14 Day Forecast", "value": _money(sum(forecast_values)), "hint": "Moving average projection"},
                {"label": "Daily Run Rate", "value": _money(avg), "hint": "Recent average revenue"},
                {"label": "Forecast Horizon", "value": "14 days", "hint": "Shown inside Power BI page"},
                {"label": "Models", "value": "3", "hint": "Prophet, ARIMA, LSTM demo comparison"},
            ],
            "charts": [
                {
                    "title": "Historical Revenue vs Forecast",
                    "type": "line",
                    "labels": labels,
                    "datasets": [
                        {"label": "Historical Revenue", "data": historical_series, "borderColor": "#2563eb", "backgroundColor": "rgba(37,99,235,.12)"},
                        {"label": "Forecast Revenue", "data": forecast_series, "borderColor": "#f59e0b", "backgroundColor": "rgba(245,158,11,.16)", "borderDash": [6, 4]},
                    ],
                },
                {
                    "title": "Model Accuracy Snapshot",
                    "type": "bar",
                    "labels": ["Prophet", "ARIMA", "LSTM"],
                    "datasets": [
                        {"label": "Accuracy %", "data": [88, 82, 85], "backgroundColor": ["#10b981", "#06b6d4", "#8b5cf6"]},
                    ],
                },
            ],
            "tables": [
                {
                    "title": "Forecast Values",
                    "headers": ["Date", "Forecast Revenue"],
                    "rows": [[label, _money(value)] for label, value in zip(forecast_labels, forecast_values)],
                }
            ],
            "insights": ["Forecast uses current order history for a fast dashboard preview.", "Use the dedicated forecasting page for full model training runs."],
        }

    if dashboard_id == "anomaly_detection":
        fraud_metrics = anomaly_detection_service.get_fraud_metrics(db)
        anomaly_report = anomaly_detection_service.get_comprehensive_anomaly_report(db)
        alerts = analytics["anomaly_alerts"]
        risk_items = anomaly_report.get("anomalies", []) if isinstance(anomaly_report, dict) else []
        severity_counts = Counter([a.get("severity", "unknown") for a in (alerts + risk_items)])
        return {
            "cards": [
                {"label": "Risk Alerts", "value": len(alerts) + len(risk_items), "hint": "Detected from order patterns"},
                {"label": "Fraud Score", "value": fraud_metrics.get("fraud_score", fraud_metrics.get("risk_score", 0)), "hint": "Current risk indicator"},
                {"label": "High Severity", "value": severity_counts.get("high", 0), "hint": "Needs attention"},
                {"label": "Cancelled Orders", "value": status_breakdown.get("Cancelled", 0), "hint": "Cancellation signal"},
            ],
            "charts": [
                {
                    "title": "Alert Severity",
                    "type": "doughnut",
                    "labels": list(severity_counts.keys()) or ["none"],
                    "datasets": [{"label": "Alerts", "data": list(severity_counts.values()) or [1], "backgroundColor": ["#ef4444", "#f59e0b", "#64748b"]}],
                },
                {
                    "title": "Order Status Risk View",
                    "type": "bar",
                    "labels": list(status_breakdown.keys()),
                    "datasets": [{"label": "Orders", "data": list(status_breakdown.values()), "backgroundColor": "#ef4444"}],
                },
            ],
            "tables": [
                {
                    "title": "Anomaly Feed",
                    "headers": ["Type", "Severity", "Message"],
                    "rows": [[a.get("type", "-"), a.get("severity", "-"), a.get("message", a.get("description", "-"))] for a in (alerts + risk_items)[:12]],
                }
            ],
            "insights": ["Anomaly visuals combine admin anomaly alerts and ML fraud signals."],
        }

    if dashboard_id == "customer_insights":
        customers = db.query(User).filter(User.is_admin == False).order_by(User.created_at.desc()).all()
        customer_rows = []
        for customer in customers:
            order_count = db.query(Order).filter(Order.user_id == customer.id).count()
            total_spent = db.query(func.sum(Order.total_amount)).filter(Order.user_id == customer.id).scalar() or 0
            customer_rows.append({"name": customer.name, "email": customer.email, "orders": order_count, "spent": float(total_spent)})
        top_customers = sorted(customer_rows, key=lambda row: row["spent"], reverse=True)[:8]
        growth = analytics["customer_growth"]
        return {
            "cards": [
                {"label": "Customers", "value": len(customers), "hint": "Non-admin users"},
                {"label": "Active Users", "value": metrics["active_users"], "hint": "Ordered in last 30 days"},
                {"label": "Top Customer Spend", "value": _money(top_customers[0]["spent"] if top_customers else 0), "hint": top_customers[0]["name"] if top_customers else "No customers yet"},
                {"label": "New Customer Months", "value": len(growth), "hint": "Growth window"},
            ],
            "charts": [
                {
                    "title": "Customer Growth",
                    "type": "line",
                    "labels": [g["month"] for g in growth],
                    "datasets": [{"label": "New Customers", "data": [g["new_customers"] for g in growth], "borderColor": "#8b5cf6", "backgroundColor": "rgba(139,92,246,.14)"}],
                },
                {
                    "title": "Top Customer Spend",
                    "type": "bar",
                    "labels": [c["name"] for c in top_customers],
                    "datasets": [{"label": "Spend", "data": [c["spent"] for c in top_customers], "backgroundColor": "#ec4899"}],
                },
            ],
            "tables": [
                {
                    "title": "Customer Leaderboard",
                    "headers": ["Name", "Email", "Orders", "Spend"],
                    "rows": [[c["name"], c["email"], c["orders"], _money(c["spent"])] for c in top_customers],
                }
            ],
            "insights": ["Customer analytics are pulled from registered users and order history."],
        }

    if dashboard_id == "inventory_analytics":
        total_value = db.query(func.sum(Product.price * Product.stock)).scalar() or 0
        out_of_stock = db.query(Product).filter(Product.stock == 0).count()
        categories = inventory_trends
        return {
            "cards": [
                {"label": "Inventory Value", "value": _money(total_value), "hint": "Price x stock"},
                {"label": "Products", "value": metrics["total_products"], "hint": "Catalog count"},
                {"label": "Low Stock", "value": len(low_stock), "hint": "Threshold <= 5"},
                {"label": "Out of Stock", "value": out_of_stock, "hint": "Needs replenishment"},
            ],
            "charts": [
                {
                    "title": "Stock by Category",
                    "type": "bar",
                    "labels": [c["category"] for c in categories],
                    "datasets": [{"label": "Stock", "data": [c["total_stock"] for c in categories], "backgroundColor": "#06b6d4"}],
                },
                {
                    "title": "Product Count by Category",
                    "type": "doughnut",
                    "labels": [c["category"] for c in categories],
                    "datasets": [{"label": "Products", "data": [c["total_products"] for c in categories], "backgroundColor": ["#2563eb", "#10b981", "#f59e0b", "#8b5cf6", "#ec4899", "#64748b"]}],
                },
            ],
            "tables": [
                {
                    "title": "Low Stock Alerts",
                    "headers": ["Product", "Category", "Stock", "Severity"],
                    "rows": [[p["name"], p["category"], p["stock"], p["severity"]] for p in low_stock[:12]],
                }
            ],
            "insights": ["Inventory visuals mirror the stock and low-stock data used by the inventory admin pages."],
        }

    if dashboard_id == "agent_analytics":
        status = ai_multi_agent_center.get_agent_status()
        tasks = ai_multi_agent_center.get_task_history(50).get("tasks", []) if isinstance(ai_multi_agent_center.get_task_history(1), dict) else ai_multi_agent_center.get_task_history(50)
        agents = status.get("agents", status if isinstance(status, dict) else {})
        agent_items = agents.values() if isinstance(agents, dict) else agents
        agent_names = [a.get("name", key) if isinstance(a, dict) else str(a) for key, a in (agents.items() if isinstance(agents, dict) else enumerate(agent_items))]
        task_statuses = Counter([t.get("status", "unknown") for t in tasks if isinstance(t, dict)])
        return {
            "cards": [
                {"label": "Agents", "value": len(agent_names), "hint": "Configured AI agents"},
                {"label": "Recent Tasks", "value": len(tasks), "hint": "Task history"},
                {"label": "Completed", "value": task_statuses.get("completed", 0), "hint": "Successful tasks"},
                {"label": "Running", "value": task_statuses.get("running", 0), "hint": "Active tasks"},
            ],
            "charts": [
                {
                    "title": "Task Status",
                    "type": "doughnut",
                    "labels": list(task_statuses.keys()) or ["none"],
                    "datasets": [{"label": "Tasks", "data": list(task_statuses.values()) or [1], "backgroundColor": ["#10b981", "#f59e0b", "#ef4444", "#64748b"]}],
                },
                {
                    "title": "Agent Coverage",
                    "type": "bar",
                    "labels": agent_names,
                    "datasets": [{"label": "Available", "data": [1 for _ in agent_names], "backgroundColor": "#00bcf2"}],
                },
            ],
            "tables": [
                {
                    "title": "Recent Agent Tasks",
                    "headers": ["Task", "Agent", "Status"],
                    "rows": [[t.get("task_type", "-"), t.get("agent_name", "-"), t.get("status", "-")] for t in tasks[:12] if isinstance(t, dict)],
                }
            ],
            "insights": ["Agent analytics are pulled from the multi-agent control center runtime state."],
        }

    return {"cards": [], "charts": [], "tables": [], "insights": ["Select a dashboard to view analytics."]}

@router.get("/api/admin/powerbi/dashboards")
def get_powerbi_dashboards(request: Request, db: Session = Depends(get_db)):
    """Get all available Power BI dashboards"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    dashboards = powerbi_service.get_all_dashboards()
    summary = powerbi_service.get_dashboard_summary()
    
    return JSONResponse({
        "dashboards": dashboards,
        "summary": summary
    })


@router.get("/api/admin/powerbi/dashboards/{dashboard_id}/embed")
def get_dashboard_embed_config(dashboard_id: str, request: Request, db: Session = Depends(get_db)):
    """Get dashboard embed configuration"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    config = powerbi_service.get_dashboard_config(dashboard_id, user.email)
    
    if not config:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    
    return JSONResponse(config)


@router.post("/api/admin/powerbi/dashboards/{dashboard_id}/refresh")
def refresh_dashboard_data(dashboard_id: str, request: Request, db: Session = Depends(get_db)):
    """Trigger dashboard data refresh"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    result = powerbi_service.refresh_dashboard_data(dashboard_id)
    return JSONResponse(result)


@router.get("/api/admin/powerbi/dashboards/{dashboard_id}/export")
def export_dashboard(dashboard_id: str, request: Request, format: str = "pdf", db: Session = Depends(get_db)):
    """Export dashboard"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    result = powerbi_service.export_dashboard(dashboard_id, format)
    return JSONResponse(result)


@router.get("/api/admin/powerbi/dashboards/{dashboard_id}/metrics")
def get_dashboard_metrics(dashboard_id: str, request: Request, db: Session = Depends(get_db)):
    """Get dashboard usage metrics"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    metrics = powerbi_service.get_dashboard_metrics(dashboard_id)
    return JSONResponse(metrics)


@router.get("/api/admin/powerbi/dashboards/{dashboard_id}/visuals")
def get_dashboard_visuals(dashboard_id: str, request: Request, db: Session = Depends(get_db)):
    """Get real in-app analytics visuals for the selected Power BI dashboard."""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    config = powerbi_service.get_dashboard_config(dashboard_id, user.email)
    if not config:
        raise HTTPException(status_code=404, detail="Dashboard not found")

    visuals = _build_powerbi_visuals(dashboard_id, db)
    visuals.update({
        "dashboard_id": dashboard_id,
        "name": config["name"],
        "description": config["description"],
        "pages": config["pages"],
        "generated_at": datetime.utcnow().isoformat(),
    })
    return JSONResponse(visuals)


@router.get("/api/admin/powerbi/analytics")
def get_powerbi_comprehensive_analytics(request: Request, db: Session = Depends(get_db)):
    """Get comprehensive Power BI analytics"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    analytics = powerbi_service.get_comprehensive_analytics()
    return JSONResponse(analytics)


@router.get("/admin/powerbi", response_class=HTMLResponse)
def admin_powerbi_analytics(request: Request, db: Session = Depends(get_db)):
    """Power BI Analytics Dashboard"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    return templates.TemplateResponse(
        "admin_powerbi_analytics.html",
        {
            "request": request,
            "user": user,
            "current_product_id": None,
        },
    )


# ───────────────────────────────────────────────────────────────────────────────
# USERS & CRM ROUTES
# ───────────────────────────────────────────────────────────────────────────────

@router.get("/admin/customers", response_class=HTMLResponse)
def admin_customers(request: Request, db: Session = Depends(get_db)):
    """Customer Management page"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    # Get all customers (non-admin users)
    customers = db.query(User).filter(User.is_admin == False).order_by(User.created_at.desc()).all()
    
    # Calculate statistics
    total_customers = len(customers)
    new_this_month = len([c for c in customers if c.created_at and c.created_at.month == datetime.now().month])
    
    # Calculate total revenue from all orders
    total_revenue = db.query(func.sum(Order.total_amount)).scalar() or 0
    
    # Get customer order counts and total spent across all orders
    customer_stats = []
    for customer in customers:
        order_count = db.query(Order).filter(Order.user_id == customer.id).count()
        total_spent = db.query(func.sum(Order.total_amount)).filter(Order.user_id == customer.id).scalar() or 0
        customer_stats.append({
            "customer": customer,
            "order_count": order_count,
            "total_spent": total_spent
        })
    
    return templates.TemplateResponse(
        "admin_customers.html",
        {
            "request": request,
            "user": user,
            "customer_stats": customer_stats,
            "total_customers": total_customers,
            "new_this_month": new_this_month,
            "total_revenue": total_revenue,
            "current_product_id": None,
        },
    )


@router.get("/api/admin/customers")
def api_get_customers(request: Request, search: str = None, db: Session = Depends(get_db)):
    """API to get customers with search"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    query = db.query(User).filter(User.is_admin == False)
    
    if search:
        search = f"%{search}%"
        query = query.filter(
            (User.name.ilike(search)) | (User.email.ilike(search)) | (User.phone.ilike(search))
        )
    
    customers = query.order_by(User.created_at.desc()).all()
    
    result = []
    for c in customers:
        order_count = db.query(Order).filter(Order.user_id == c.id).count()
        total_spent = db.query(Order).filter(Order.user_id == c.id, Order.payment_status.in_(["Paid", "Completed"])).with_entities(func.sum(Order.total_amount)).scalar() or 0
        result.append({
            "id": c.id,
            "name": c.name,
            "email": c.email,
            "phone": c.phone,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "order_count": order_count,
            "total_spent": float(total_spent)
        })
    
    return JSONResponse(result)


@router.get("/api/admin/customers/{customer_id}/details")
def api_get_customer_details(customer_id: int, request: Request, db: Session = Depends(get_db)):
    """Get detailed customer information with orders"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    customer = db.query(User).filter(User.id == customer_id, User.is_admin == False).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    orders = db.query(Order).filter(Order.user_id == customer_id).order_by(Order.created_at.desc()).all()
    activities = db.query(UserActivity).filter(UserActivity.user_id == customer_id).order_by(UserActivity.created_at.desc()).limit(20).all()
    
    return JSONResponse({
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "email": customer.email,
            "phone": customer.phone,
            "created_at": customer.created_at.isoformat() if customer.created_at else None,
        },
        "orders": [{
            "id": o.id,
            "order_number": o.order_number,
            "total_amount": o.total_amount,
            "status": o.status,
            "payment_status": o.payment_status,
            "created_at": o.created_at.isoformat() if o.created_at else None
        } for o in orders],
        "activities": [{
            "type": a.activity_type,
            "details": a.activity_details,
            "created_at": a.created_at.isoformat() if a.created_at else None
        } for a in activities]
    })


@router.get("/admin/tickets", response_class=HTMLResponse)
def admin_support_tickets(request: Request, status: str = None, priority: str = None, db: Session = Depends(get_db)):
    """Support Tickets Management page"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    # Build query
    query = db.query(SupportTicket)
    
    if status:
        query = query.filter(SupportTicket.status == status)
    if priority:
        query = query.filter(SupportTicket.priority == priority)
    
    tickets = query.order_by(
        case(
            (SupportTicket.priority == "High", 1),
            (SupportTicket.priority == "Medium", 2),
            (SupportTicket.priority == "Low", 3),
            else_=4
        ),
        SupportTicket.created_at.desc()
    ).all()
    
    # Calculate statistics
    total_tickets = db.query(SupportTicket).count()
    open_tickets = db.query(SupportTicket).filter(SupportTicket.status == "Open").count()
    high_priority = db.query(SupportTicket).filter(SupportTicket.priority == "High", SupportTicket.status == "Open").count()
    resolved_today = db.query(SupportTicket).filter(
        SupportTicket.status == "Resolved",
        SupportTicket.created_at >= datetime.now().replace(hour=0, minute=0, second=0)
    ).count()
    
    return templates.TemplateResponse(
        "admin_tickets.html",
        {
            "request": request,
            "user": user,
            "tickets": tickets,
            "total_tickets": total_tickets,
            "open_tickets": open_tickets,
            "high_priority": high_priority,
            "resolved_today": resolved_today,
            "current_filter": status,
            "current_product_id": None,
        },
    )


@router.get("/api/admin/tickets")
def api_get_tickets(request: Request, status: str = None, priority: str = None, db: Session = Depends(get_db)):
    """API to get support tickets"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    query = db.query(SupportTicket)
    
    if status:
        query = query.filter(SupportTicket.status == status)
    if priority:
        query = query.filter(SupportTicket.priority == priority)
    
    tickets = query.order_by(SupportTicket.created_at.desc()).all()
    
    return JSONResponse([{
        "id": t.id,
        "ticket_number": t.ticket_number,
        "customer_email": t.customer_email,
        "subject": t.subject,
        "status": t.status,
        "priority": t.priority,
        "source": t.source,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "admin_note": t.admin_note
    } for t in tickets])


@router.get("/api/admin/tickets/{ticket_id}")
def api_get_ticket_details(ticket_id: int, request: Request, db: Session = Depends(get_db)):
    """Get ticket details"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    return JSONResponse({
        "id": ticket.id,
        "ticket_number": ticket.ticket_number,
        "customer_email": ticket.customer_email,
        "subject": ticket.subject,
        "issue": ticket.issue,
        "order_number": ticket.order_number,
        "status": ticket.status,
        "priority": ticket.priority,
        "source": ticket.source,
        "sentiment": ticket.sentiment,
        "admin_note": ticket.admin_note,
        "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
    })


@router.post("/api/admin/tickets/{ticket_id}/update")
def api_update_ticket(
    ticket_id: int,
    request: Request,
    status: str = Form(...),
    priority: str = Form(None),
    admin_note: str = Form(None),
    db: Session = Depends(get_db)
):
    """Update ticket status and notes"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    ticket = db.query(SupportTicket).filter(SupportTicket.id == ticket_id).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    
    ticket.status = status
    if priority:
        ticket.priority = priority
    if admin_note:
        ticket.admin_note = admin_note
    
    db.commit()
    
    # Log the action
    audit_log = AuditLog(
        user_id=user.id,
        action="Updated Ticket",
        entity_type="SupportTicket",
        entity_id=str(ticket_id),
        new_values=f"Status: {status}, Priority: {priority}"
    )
    db.add(audit_log)
    db.commit()
    
    return JSONResponse({
        "success": True,
        "message": "Ticket updated successfully"
    })


@router.get("/admin/feedback", response_class=HTMLResponse)
def admin_feedback(request: Request, db: Session = Depends(get_db)):
    """Customer Feedback Management page"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    # Get user activities that might contain feedback
    feedback_activities = db.query(UserActivity).filter(
        UserActivity.activity_type.in_(["feedback", "review", "review_submitted", "rating", "complaint"])
    ).order_by(UserActivity.created_at.desc()).all()
    
    return templates.TemplateResponse(
        "admin_feedback.html",
        {
            "request": request,
            "user": user,
            "feedback_activities": feedback_activities,
            "current_product_id": None,
        },
    )


@router.get("/api/admin/feedback/summary")
def api_get_feedback_summary(request: Request, db: Session = Depends(get_db)):
    """Get feedback summary statistics"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    sentiment_data = {"positive": 0, "neutral": 0, "negative": 0}

    ticket_counts = db.query(
        SupportTicket.sentiment,
        func.count(SupportTicket.id)
    ).group_by(SupportTicket.sentiment).all()

    for sentiment, count in ticket_counts:
        key = (sentiment or "neutral").lower()
        if key == "mixed":
            key = "neutral"
        if key in sentiment_data:
            sentiment_data[key] += count

    feedback_activities = db.query(UserActivity).filter(
        UserActivity.activity_type.in_(["feedback", "review", "review_submitted", "rating", "complaint"])
    ).all()

    for activity in feedback_activities:
        details = (activity.activity_details or "").lower()
        if "sentiment: positive" in details or "sentiment=positive" in details:
            sentiment_data["positive"] += 1
        elif "sentiment: negative" in details or "sentiment=negative" in details:
            sentiment_data["negative"] += 1
        elif "sentiment: neutral" in details or "sentiment=mixed" in details or "sentiment: mixed" in details:
            sentiment_data["neutral"] += 1

    return JSONResponse({
        "sentiment": sentiment_data,
        "total_feedback": sum(sentiment_data.values())
    })


# AI ASSISTANT & RECOMMENDATIONS ROUTES
# ───────────────────────────────────────────────────────────────────────────────

@router.get("/admin/chat-ai", response_class=HTMLResponse)
def admin_ai_assistant(request: Request, db: Session = Depends(get_db)):
    """AI Assistant Chat Page for Admins"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    # Check AI availability
    ai_available = ai_multi_agent_center.llm_service is not None and ai_multi_agent_center.llm_service.is_available()
    
    return templates.TemplateResponse(
        "admin_ai_assistant.html",
        {
            "request": request,
            "user": user,
            "ai_available": ai_available,
            "current_product_id": None,
        },
    )


def _get_comprehensive_context_data(message: str, db: Session) -> dict:
    """Collect comprehensive data from all available sources for AI assistant"""
    context_data = {}
    msg_lower = message.lower()
    
    # Always collect dashboard metrics as baseline
    try:
        metrics = admin_analytics_service.get_dashboard_metrics(db)
        context_data["dashboard_metrics"] = {
            "total_revenue": metrics.get("total_revenue", 0),
            "total_orders": metrics.get("total_orders", 0),
            "total_customers": metrics.get("total_customers", 0),
            "total_products": metrics.get("total_products", 0),
            "avg_order_value": metrics.get("avg_order_value", 0),
            "active_users": metrics.get("active_users", 0),
            "today_revenue": metrics.get("today_revenue", 0),
            "today_orders": metrics.get("today_orders", 0)
        }
    except Exception as e:
        logger.warning(f"Failed to get dashboard metrics: {e}")
    
    # Inventory data
    if any(word in msg_lower for word in ["inventory", "stock", "product", "warehouse"]):
        try:
            inv_result = ai_multi_agent_center.execute_task("inventory", "warehouse_analytics", {}, db)
            context_data["inventory"] = inv_result.get("result", {})
            
            # Also get direct product counts
            low_stock = db.query(Product).filter(Product.stock < 10).count()
            out_of_stock = db.query(Product).filter(Product.stock == 0).count()
            total_products = db.query(Product).count()
            context_data["inventory_summary"] = {
                "total_products": total_products,
                "low_stock_count": low_stock,
                "out_of_stock_count": out_of_stock
            }
        except Exception as e:
            logger.warning(f"Failed to get inventory data: {e}")
    
    # Sales/Revenue data
    if any(word in msg_lower for word in ["sales", "revenue", "order", "income", "money"]):
        try:
            retail_result = ai_multi_agent_center.execute_task("retail_analyst", "sales_trend_analysis", {"days": 30}, db)
            context_data["retail"] = retail_result.get("result", {})
            
            # Get recent orders summary
            recent_orders = db.query(Order).order_by(Order.created_at.desc()).limit(5).all()
            context_data["recent_orders"] = [
                {
                    "order_number": o.order_number,
                    "status": o.status,
                    "amount": float(o.total_amount),
                    "date": o.created_at.strftime("%Y-%m-%d") if o.created_at else None
                }
                for o in recent_orders
            ]
        except Exception as e:
            logger.warning(f"Failed to get retail data: {e}")
    
    # Customer data
    if any(word in msg_lower for word in ["customer", "user", "buyer", "client"]):
        try:
            total_users = db.query(User).count()
            new_users_30d = db.query(User).filter(User.created_at >= datetime.utcnow() - timedelta(days=30)).count()
            
            # Customer segmentation
            segments = customer_segmentation_service.get_all_customer_segments(db)
            context_data["customers"] = {
                "total_users": total_users,
                "new_users_30d": new_users_30d,
                "segments": segments
            }
        except Exception as e:
            logger.warning(f"Failed to get customer data: {e}")
    
    # Forecasting data
    if any(word in msg_lower for word in ["forecast", "predict", "future", "trend", "projection"]):
        try:
            forecast = demand_forecasting_service.forecast_revenue(db, days=30)
            context_data["forecast"] = {
                "trend": forecast.get("trend", "stable"),
                "confidence": forecast.get("confidence_intervals", {}).get("average", 0),
                "daily_forecasts_count": len(forecast.get("daily_forecasts", []))
            }
        except Exception as e:
            logger.warning(f"Failed to get forecast data: {e}")
    
    # Anomalies data
    if any(word in msg_lower for word in ["anomaly", "anomalies", "fraud", "unusual", "alert"]):
        try:
            anomalies = anomaly_detection_service.detect_order_anomalies(db)
            context_data["anomalies"] = {
                "count": len(anomalies.get("anomalies", [])),
                "high_severity": len([a for a in anomalies.get("anomalies", []) if a.get("severity") == "high"])
            }
        except Exception as e:
            logger.warning(f"Failed to get anomalies data: {e}")
    
    # Tickets/Support data
    if any(word in msg_lower for word in ["ticket", "support", "complaint", "issue", "help"]):
        try:
            open_tickets = db.query(SupportTicket).filter(SupportTicket.status == "Open").count()
            high_priority = db.query(SupportTicket).filter(
                SupportTicket.status == "Open",
                SupportTicket.priority == "High"
            ).count()
            context_data["support"] = {
                "open_tickets": open_tickets,
                "high_priority": high_priority
            }
        except Exception as e:
            logger.warning(f"Failed to get support data: {e}")
    
    return context_data


def _generate_rule_based_response(message: str, context_data: dict, db: Session) -> str:
    """Generate a helpful response using rule-based logic when AI is unavailable"""
    msg_lower = message.lower()
    
    # Check for specific query types and provide data-rich responses
    if any(word in msg_lower for word in ["dashboard", "summary", "overview", "metrics"]):
        metrics = context_data.get("dashboard_metrics", {})
        return f"""Here's your current dashboard summary:

📊 **Key Metrics:**
• Total Revenue: ₹{metrics.get('total_revenue', 0):,.2f}
• Total Orders: {metrics.get('total_orders', 0):,}
• Average Order Value: ₹{metrics.get('avg_order_value', 0):,.2f}
• Total Customers: {metrics.get('total_customers', 0):,}
• Total Products: {metrics.get('total_products', 0):,}

📈 **Today's Activity:**
• Revenue Today: ₹{metrics.get('today_revenue', 0):,.2f}
• Orders Today: {metrics.get('today_orders', 0)}
• Active Users (30d): {metrics.get('active_users', 0)}

Is there a specific metric you'd like me to explain or analyze further?"""
    
    if any(word in msg_lower for word in ["inventory", "stock", "product"]):
        inv = context_data.get("inventory_summary", {})
        return f"""Here's your current inventory status:

📦 **Inventory Summary:**
• Total Products: {inv.get('total_products', 0)}
• Low Stock Items (< 10): {inv.get('low_stock_count', 0)}
• Out of Stock: {inv.get('out_of_stock_count', 0)}

Use the Inventory AI Dashboard to see detailed analytics and restock recommendations."""
    
    if any(word in msg_lower for word in ["customer", "user"]):
        cust = context_data.get("customers", {})
        segments = cust.get("segments", {})
        return f"""Here's your customer overview:

👥 **Customer Metrics:**
• Total Users: {cust.get('total_users', 0):,}
• New Users (30 days): {cust.get('new_users_30d', 0)}

📊 **Customer Segments:**
{chr(10).join([f"• {k.replace('_', ' ').title()}: {v}" for k, v in list(segments.items())[:5]])}

Visit the Customers Analytics page for detailed insights and segmentation analysis."""
    
    if any(word in msg_lower for word in ["order", "sales", "revenue"]):
        recent = context_data.get("recent_orders", [])
        metrics = context_data.get("dashboard_metrics", {})
        recent_str = "\n".join([f"• {o['order_number']} - {o['status']} - ₹{o['amount']:.0f}" for o in recent[:3]])
        return f"""Here's your sales overview:

💰 **Sales Summary:**
• Total Revenue: ₹{metrics.get('total_revenue', 0):,.2f}
• Total Orders: {metrics.get('total_orders', 0):,}
• Average Order Value: ₹{metrics.get('avg_order_value', 0):,.2f}

📦 **Recent Orders:**
{recent_str}

Would you like to see more detailed analytics or check specific order details?"""
    
    if any(word in msg_lower for word in ["forecast", "predict"]):
        forecast = context_data.get("forecast", {})
        return f"""Here's your demand forecast:

📈 **Forecast Summary:**
• Trend Direction: {forecast.get('trend', 'stable').title()}
• Confidence Level: {forecast.get('confidence', 0)}%
• Forecast Period: 30 days

Visit the Demand Forecasting page for detailed daily predictions and trend analysis."""
    
    if any(word in msg_lower for word in ["ticket", "support"]):
        support = context_data.get("support", {})
        return f"""Here's your support overview:

🎫 **Support Tickets:**
• Open Tickets: {support.get('open_tickets', 0)}
• High Priority: {support.get('high_priority', 0)}

Check the Support Tickets page to view and manage all customer inquiries."""
    
    # Default helpful response
    return """I'm here to help you with your e-commerce admin tasks! I can provide information about:

📊 **Dashboard Metrics** - Revenue, orders, customers
📦 **Inventory** - Stock levels, low stock alerts
👥 **Customers** - User segments, growth metrics
📈 **Sales & Orders** - Order tracking, revenue trends
🔮 **Forecasting** - Demand predictions
🎫 **Support Tickets** - Customer service metrics
🤖 **AI Agents** - Multi-agent insights

What would you like to know about?"""


@router.post("/api/admin/ai-assistant/chat")
def api_ai_assistant_chat(request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    """AI Assistant chat endpoint with multi-agent orchestration"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    message = payload.get("message", "")
    context = payload.get("context", {})
    
    if not message:
        return JSONResponse({"error": "Message is required"}, status_code=400)
    
    try:
        # Debug: Check AI service status
        llm_service = ai_multi_agent_center.llm_service
        is_available = llm_service.is_available() if llm_service else False
        
        logger.info(f"AI Assistant request - LLM service: {llm_service is not None}, Available: {is_available}")
        
        # Collect comprehensive data regardless of AI availability
        context_data = _get_comprehensive_context_data(message, db)
        
        # Use the AI multi-agent system for intelligent responses
        if llm_service and is_available:
            try:
                # Determine intent
                intent_result = llm_service.generate_response(
                    prompt=f"Classify this admin query into one of: inventory, retail_analytics, customers, forecasting, support, general. Query: {message}",
                    system_prompt="You are a query classifier. Respond with only the category name."
                )
                
                if not intent_result.get("success"):
                    intent = "general"
                else:
                    intent = intent_result.get("response", "general").strip().lower()
                
                # Generate AI response with comprehensive context
                system_prompt = """You are an AI Assistant for StyleHub AI e-commerce admin panel.
Your role is to help administrators manage their store effectively.

Guidelines:
- Always provide specific data from the context when available
- If data is limited, provide what's available and suggest where to find more
- Be helpful, concise, and professional
- Offer actionable insights based on the data
- If asked about something not in the context, use general e-commerce knowledge to help

Available data sources include: dashboard metrics, inventory, customers, sales, orders, forecasting, anomalies, and support tickets."""
                
                context_str = json.dumps(context_data, indent=2, default=str)[:3000]
                
                ai_result = llm_service.generate_with_rag(
                    query=f"User query: {message}\n\nAvailable data:\n{context_str}\n\nPlease provide a helpful response with specific data where possible.",
                    system_prompt=system_prompt,
                    k=3
                )
                
                if ai_result.get("success"):
                    return JSONResponse({
                        "success": True,
                        "response": ai_result.get("response", "I apologize, I couldn't generate a response."),
                        "intent": intent,
                        "rag_enhanced": ai_result.get("rag_used", False),
                        "model": ai_result.get("model", "unknown"),
                        "data_sources": list(context_data.keys()),
                        "timestamp": datetime.utcnow().isoformat()
                    })
                else:
                    # AI generation failed, use rule-based fallback
                    logger.warning(f"AI generation failed: {ai_result.get('error')}. Using rule-based fallback.")
                    fallback_response = _generate_rule_based_response(message, context_data, db)
                    return JSONResponse({
                        "success": True,
                        "response": fallback_response,
                        "intent": intent,
                        "ai_used": False,
                        "fallback_reason": ai_result.get("error"),
                        "data_sources": list(context_data.keys()),
                        "timestamp": datetime.utcnow().isoformat()
                    })
                
            except Exception as inner_e:
                logger.error(f"AI processing error: {inner_e}")
                # Fallback to rule-based response
                fallback_response = _generate_rule_based_response(message, context_data, db)
                return JSONResponse({
                    "success": True,
                    "response": fallback_response,
                    "intent": "general",
                    "ai_used": False,
                    "fallback_reason": str(inner_e),
                    "data_sources": list(context_data.keys()),
                    "timestamp": datetime.utcnow().isoformat()
                })
        else:
            # AI not available - use rule-based response with collected data
            error_msg = "LLM service not initialized" if not llm_service else "OpenAI API key not configured"
            logger.warning(f"AI Assistant offline: {error_msg}. Using rule-based fallback.")
            
            rule_response = _generate_rule_based_response(message, context_data, db)
            
            return JSONResponse({
                "success": True,
                "response": rule_response,
                "ai_available": False,
                "note": "AI Assistant is running in fallback mode with real-time data from your store.",
                "data_sources": list(context_data.keys()),
                "timestamp": datetime.utcnow().isoformat()
            })
            
    except Exception as e:
        logger.error(f"AI Assistant error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return JSONResponse({
            "success": False,
            "error": str(e),
            "response": "I encountered a system error. Please try again or check the specific dashboard pages for the information you need."
        }, status_code=500)


@router.get("/admin/recommendations", response_class=HTMLResponse)
def admin_recommendations(request: Request, db: Session = Depends(get_db)):
    """AI-Powered Recommendations Dashboard"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    # Get current products for recommendation base
    products = db.query(Product).filter(Product.stock > 0).limit(20).all()
    
    # Check AI availability
    ai_available = ai_multi_agent_center.llm_service is not None and ai_multi_agent_center.llm_service.is_available()
    
    return templates.TemplateResponse(
        "admin_recommendations.html",
        {
            "request": request,
            "user": user,
            "products": products,
            "ai_available": ai_available,
            "current_product_id": None,
        },
    )


def get_or_create_setting(db: Session, key: str, default_value: str, setting_type: str = "string", description: str = ""):
    """Helper to get or create system settings"""
    setting = db.query(SystemSettings).filter(SystemSettings.setting_key == key).first()
    if not setting:
        setting = SystemSettings(
            setting_key=key,
            setting_value=default_value,
            setting_type=setting_type,
            description=description
        )
        db.add(setting)
        db.commit()
        db.refresh(setting)
    return setting


@router.get("/admin/settings", response_class=HTMLResponse)
def admin_settings(request: Request, db: Session = Depends(get_db)):
    """Admin Settings Page"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    # Initialize default settings if they don't exist
    settings_data = {
        'store_name': get_or_create_setting(db, 'store_name', 'StyleHub AI', 'string', 'Store display name'),
        'support_email': get_or_create_setting(db, 'support_email', 'support@stylehub.ai', 'string', 'Support email address'),
        'timezone': get_or_create_setting(db, 'timezone', 'Asia/Kolkata', 'string', 'System timezone'),
        'email_notifications': get_or_create_setting(db, 'email_notifications', 'true', 'bool', 'Enable email notifications'),
        'order_alerts': get_or_create_setting(db, 'order_alerts', 'true', 'bool', 'Enable new order alerts'),
        'ticket_alerts': get_or_create_setting(db, 'ticket_alerts', 'true', 'bool', 'Enable support ticket alerts'),
        'low_stock_alerts': get_or_create_setting(db, 'low_stock_alerts', 'true', 'bool', 'Enable low stock warnings'),
    }
    
    return templates.TemplateResponse(
        "admin_settings.html",
        {
            "request": request,
            "user": user,
            "settings": settings_data,
            "current_product_id": None,
        },
    )


@router.post("/api/admin/settings/save")
def save_settings(request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Save system settings"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return JSONResponse({"error": "Admin access required"}, status_code=403)
    
    try:
        settings_to_save = payload.get('settings', {})
        for key, value in settings_to_save.items():
            setting = db.query(SystemSettings).filter(SystemSettings.setting_key == key).first()
            if setting:
                setting.setting_value = str(value)
                setting.updated_by = user.id
                setting.updated_at = datetime.utcnow()
            else:
                setting = SystemSettings(
                    setting_key=key,
                    setting_value=str(value),
                    updated_by=user.id
                )
                db.add(setting)
        
        db.commit()
        
        # Log the action
        audit_log = AuditLog(
            user_id=user.id,
            action="UPDATE_SETTINGS",
            entity_type="system_settings",
            entity_id="global",
            new_values=json.dumps(settings_to_save),
            ip_address=request.client.host if request.client else None
        )
        db.add(audit_log)
        db.commit()
        
        return JSONResponse({"success": True, "message": "Settings saved successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/admin/security", response_class=HTMLResponse)
def admin_security(request: Request, db: Session = Depends(get_db)):
    """Admin Security Page"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    # Get real access logs from AuditLog and UserActivity
    access_logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(50).all()
    
    # Get active sessions
    active_sessions = db.query(UserSession).filter(
        UserSession.is_active == True,
        UserSession.expires_at > datetime.utcnow()
    ).order_by(UserSession.created_at.desc()).limit(20).all()
    
    # Get security settings
    security_settings = {
        'strong_passwords': get_or_create_setting(db, 'strong_passwords', 'true', 'bool', 'Require strong passwords'),
        'password_expiry': get_or_create_setting(db, 'password_expiry', 'false', 'bool', 'Enable password expiry'),
        'min_password_length': get_or_create_setting(db, 'min_password_length', '8', 'int', 'Minimum password length'),
        'session_timeout': get_or_create_setting(db, 'session_timeout', '30', 'int', 'Session timeout in minutes'),
        'admin_2fa': get_or_create_setting(db, 'admin_2fa', 'false', 'bool', 'Require 2FA for admins'),
        'single_session': get_or_create_setting(db, 'single_session', 'false', 'bool', 'Single session per user'),
    }
    
    return templates.TemplateResponse(
        "admin_security.html",
        {
            "request": request,
            "user": user,
            "access_logs": access_logs,
            "active_sessions": active_sessions,
            "security_settings": security_settings,
            "current_product_id": None,
        },
    )


@router.post("/api/admin/security/save")
def save_security_settings(request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Save security settings"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return JSONResponse({"error": "Admin access required"}, status_code=403)
    
    try:
        settings_to_save = payload.get('settings', {})
        for key, value in settings_to_save.items():
            setting = db.query(SystemSettings).filter(SystemSettings.setting_key == key).first()
            if setting:
                setting.setting_value = str(value)
                setting.updated_by = user.id
                setting.updated_at = datetime.utcnow()
            else:
                setting = SystemSettings(
                    setting_key=key,
                    setting_value=str(value),
                    updated_by=user.id
                )
                db.add(setting)
        
        db.commit()
        
        # Log the action
        audit_log = AuditLog(
            user_id=user.id,
            action="UPDATE_SECURITY_SETTINGS",
            entity_type="security_settings",
            entity_id="global",
            new_values=json.dumps(settings_to_save),
            ip_address=request.client.host if request.client else None
        )
        db.add(audit_log)
        db.commit()
        
        return JSONResponse({"success": True, "message": "Security settings saved successfully"})
    except Exception as e:
        db.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/admin/security/logs")
def get_security_logs(request: Request, limit: int = 50, db: Session = Depends(get_db)):
    """Get security audit logs"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return JSONResponse({"error": "Admin access required"}, status_code=403)
    
    logs = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()
    
    return JSONResponse({
        "logs": [
            {
                "id": log.id,
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "ip_address": log.ip_address,
                "created_at": log.created_at.isoformat() if log.created_at else None,
                "user_id": log.user_id
            }
            for log in logs
        ]
    })


@router.post("/api/admin/recommendations/generate")
def api_generate_recommendations(request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Generate AI-powered recommendations"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    recommendation_type = payload.get("type", "products")
    params = payload.get("params", {})
    
    try:
        recommendations = []
        
        if recommendation_type == "products":
            # Get product performance data
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            top_products = db.query(
                Product.id,
                Product.name,
                Product.category,
                Product.price,
                Product.stock,
                func.sum(OrderItem.quantity).label('units_sold'),
                func.sum(OrderItem.quantity * OrderItem.unit_price).label('revenue')
            ).join(OrderItem, Product.id == OrderItem.product_id).join(
                Order, OrderItem.order_id == Order.id
            ).filter(
                Order.created_at >= thirty_days_ago,
                Order.status.in_(['Delivered', 'Shipped'])
            ).group_by(Product.id).order_by(func.sum(OrderItem.quantity).desc()).limit(10).all()
            
            # Get AI insights on top products
            if ai_multi_agent_center.llm_service and ai_multi_agent_center.llm_service.is_available():
                product_data = [
                    {
                        "name": p.name,
                        "category": p.category,
                        "price": float(p.price),
                        "stock": p.stock,
                        "units_sold": p.units_sold,
                        "revenue": float(p.revenue)
                    }
                    for p in top_products
                ]
                
                ai_result = ai_multi_agent_center.llm_service.analyze_data_with_llm(
                    {"top_products": product_data},
                    "product recommendations",
                    "Analyze these top-performing products and recommend similar products to promote, pricing strategies, and inventory adjustments."
                )
                
                ai_insights = ai_result.get("response", "AI insights unavailable")
            else:
                ai_insights = "AI insights unavailable - configure OPENAI_API_KEY"
            
            recommendations = [
                {
                    "type": "product",
                    "title": p.name,
                    "category": p.category,
                    "price": float(p.price),
                    "stock": p.stock,
                    "performance_score": float(p.revenue) * 0.7 + p.units_sold * 0.3,
                    "action": "Promote" if p.stock > 20 else "Restock & Promote"
                }
                for p in top_products[:5]
            ]
            
        elif recommendation_type == "inventory":
            # Get inventory recommendations
            result = ai_multi_agent_center.execute_task("inventory", "recommend_reorder", params, db)
            recs = result.get("result", {}).get("recommendations", [])
            
            recommendations = [
                {
                    "type": "inventory",
                    "product_id": r["product_id"],
                    "title": r["name"],
                    "action": f"Reorder {r['recommended_quantity']} units",
                    "priority": r["priority"],
                    "reason": f"Current stock: {r['current_stock']}, Reorder point: {r['reorder_point']}"
                }
                for r in recs[:10]
            ]
            
            ai_insights = result.get("result", {}).get("ai_strategy", "AI insights unavailable")
            
        elif recommendation_type == "pricing":
            # Generate pricing recommendations
            products_analysis = db.query(Product).all()
            
            pricing_recs = []
            for product in products_analysis:
                avg_price = db.query(func.avg(OrderItem.unit_price)).filter(
                    OrderItem.product_id == product.id
                ).scalar() or product.price
                
                if avg_price > product.price * 1.1:
                    pricing_recs.append({
                        "type": "pricing",
                        "product_id": product.id,
                        "title": product.name,
                        "action": "Increase Price",
                        "current_price": float(product.price),
                        "suggested_price": round(float(avg_price), 2),
                        "reason": "Selling above current price point"
                    })
            
            recommendations = pricing_recs[:5]
            ai_insights = f"Found {len(pricing_recs)} products with pricing optimization opportunities"
        
        return JSONResponse({
            "success": True,
            "type": recommendation_type,
            "recommendations": recommendations,
            "ai_insights": ai_insights,
            "total": len(recommendations),
            "generated_at": datetime.utcnow().isoformat(),
            "processing_info": {
                "agents_used": ["inventory", "retail_analyst", "ml_insights"] if ai_multi_agent_center.llm_service and ai_multi_agent_center.llm_service.is_available() else ["inventory"],
                "ai_enhanced": ai_multi_agent_center.llm_service is not None and ai_multi_agent_center.llm_service.is_available(),
                "data_source": "real_time_database",
                "cache_used": False
            }
        })
        
    except Exception as e:
        logger.error(f"Recommendations error: {e}")
        return JSONResponse({
            "success": False,
            "error": str(e)
        }, status_code=500)


@router.get("/api/admin/ai-health")
def api_ai_health_check(request: Request, db: Session = Depends(get_db)):
    """Health check for AI services"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    health_status = {
        "timestamp": datetime.utcnow().isoformat(),
        "services": {}
    }
    
    # Check LLM Service
    try:
        llm_service = ai_multi_agent_center.llm_service
        if llm_service:
            health_status["services"]["llm_service"] = {
                "initialized": True,
                "api_key_configured": bool(llm_service.config.openai_api_key),
                "api_key_preview": llm_service.config.openai_api_key[:10] + "..." if llm_service.config.openai_api_key else None,
                "model": llm_service.config.model,
                "available": llm_service.is_available()
            }
        else:
            health_status["services"]["llm_service"] = {
                "initialized": False,
                "error": "LLM service not initialized"
            }
    except Exception as e:
        health_status["services"]["llm_service"] = {
            "error": str(e)
        }
    
    # Check Vector Store
    try:
        vectorstore = ai_multi_agent_center.llm_service.vectorstore if ai_multi_agent_center.llm_service else None
        health_status["services"]["vectorstore"] = {
            "initialized": vectorstore is not None,
            "available": vectorstore is not None and vectorstore.vectorstore is not None
        }
    except Exception as e:
        health_status["services"]["vectorstore"] = {
            "error": str(e)
        }
    
    # Check Agents
    try:
        agents_status = ai_multi_agent_center.get_agent_status()
        health_status["services"]["agents"] = agents_status
    except Exception as e:
        health_status["services"]["agents"] = {
            "error": str(e)
        }
    
    return JSONResponse(health_status)


# ==================== Power BI Analytics Routes ====================

@router.get("/admin/powerbi", response_class=HTMLResponse)
def admin_powerbi_dashboard(request: Request, db: Session = Depends(get_db)):
    """Power BI Analytics Dashboard Page"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    return templates.TemplateResponse(
        "admin_powerbi_analytics.html",
        {
            "request": request,
            "user": user,
            "current_product_id": None,
        },
    )


@router.get("/api/admin/powerbi/dashboards")
def get_powerbi_dashboards(request: Request, db: Session = Depends(get_db)):
    """Get all available Power BI dashboards"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    dashboards = powerbi_service.get_all_dashboards()
    return JSONResponse({"dashboards": dashboards})


@router.get("/api/admin/powerbi/dashboards/{dashboard_id}/visuals")
def get_powerbi_dashboard_visuals(dashboard_id: str, request: Request, db: Session = Depends(get_db)):
    """Get Power BI dashboard visuals with real data"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # Get dashboard config
    dashboard_config = powerbi_service.get_dashboard_config(dashboard_id)
    if not dashboard_config:
        raise HTTPException(status_code=404, detail="Dashboard not found")
    
    # Get real data based on dashboard type
    from app.services.admin_analytics_service import admin_analytics_service
    
    if dashboard_id == "sales_analytics":
        data = _get_sales_analytics_data(db, admin_analytics_service)
    elif dashboard_id == "forecasting":
        data = _get_forecasting_data(db)
    elif dashboard_id == "anomaly_detection":
        data = _get_anomaly_data(db)
    elif dashboard_id == "customer_insights":
        data = _get_customer_insights_data(db)
    elif dashboard_id == "inventory_analytics":
        data = _get_inventory_analytics_data(db, admin_analytics_service)
    elif dashboard_id == "agent_analytics":
        data = _get_agent_analytics_data(db)
    else:
        data = _get_default_dashboard_data(db, dashboard_config)
    
    return JSONResponse(data)


def _get_sales_analytics_data(db: Session, admin_service):
    """Get sales analytics dashboard data"""
    metrics = admin_service.get_dashboard_metrics(db)
    revenue_trends = admin_service.get_revenue_trends(db, days=30)
    top_products = admin_service.get_top_selling_products(db, limit=10)
    
    # Format for charts
    dates = [r["date"] for r in revenue_trends]
    revenues = [r["revenue"] for r in revenue_trends]
    orders = [r["orders"] for r in revenue_trends]
    
    return {
        "id": "sales_analytics",
        "name": "Sales Analytics",
        "description": "Comprehensive sales performance analytics",
        "pages": ["Overview", "Trends", "Products", "Regions"],
        "cards": [
            {"label": "Total Revenue", "value": f"₹{metrics['total_revenue']:,.0f}", "hint": f"Today: ₹{metrics['today_revenue']:,.0f}"},
            {"label": "Total Orders", "value": f"{metrics['total_orders']:,}", "hint": f"Today: {metrics['today_orders']}"},
            {"label": "Active Users", "value": f"{metrics['active_users']:,}", "hint": "Last 30 days"},
            {"label": "Avg Order Value", "value": f"₹{metrics['avg_order_value']:,.0f}", "hint": "Per order"}
        ],
        "charts": [
            {
                "title": "Revenue Trends (30 Days)",
                "type": "line",
                "labels": dates,
                "datasets": [
                    {"label": "Revenue (₹)", "data": revenues, "borderColor": "#2563eb", "backgroundColor": "rgba(37, 99, 235, 0.1)", "fill": True}
                ]
            },
            {
                "title": "Orders vs Revenue",
                "type": "bar",
                "labels": dates[-7:],  # Last 7 days
                "datasets": [
                    {"label": "Orders", "data": orders[-7:], "backgroundColor": "#10b981", "yAxisID": "y"},
                    {"label": "Revenue (₹1000s)", "data": [r/1000 for r in revenues[-7:]], "backgroundColor": "#2563eb", "yAxisID": "y1"}
                ]
            }
        ],
        "tables": [
            {
                "title": "Top Selling Products",
                "headers": ["Product", "Category", "Sold", "Revenue"],
                "rows": [[p["name"], p["category"], p["total_sold"], f"₹{p['total_revenue']:,.0f}"] for p in top_products[:8]]
            }
        ],
        "insights": [
            f"Revenue this month: ₹{metrics['total_revenue']:,.0f}",
            f"Average order value: ₹{metrics['avg_order_value']:,.0f}",
            f"Total customers: {metrics['total_customers']:,}",
            f"Active users (30d): {metrics['active_users']:,}"
        ],
        "generated_at": datetime.utcnow().isoformat()
    }


def _get_forecasting_data(db: Session):
    """Get forecasting dashboard data"""
    from app.services.demand_forecasting_service import demand_forecasting_service
    
    forecast = demand_forecasting_service.forecast_revenue(db, days=30)
    daily_forecasts = forecast.get("daily_forecasts", [])
    
    dates = [f["date"] for f in daily_forecasts]
    predictions = [f["forecast"] for f in daily_forecasts]
    
    # Calculate confidence intervals
    upper = [f["upper"] for f in daily_forecasts] if daily_forecasts else []
    lower = [f["lower"] for f in daily_forecasts] if daily_forecasts else []
    
    total_forecast = sum(predictions) if predictions else 0
    
    return {
        "id": "forecasting",
        "name": "Demand Forecasting",
        "description": "AI-powered demand and revenue forecasting",
        "pages": ["Revenue Forecast", "Product Demand", "Seasonal Trends", "Accuracy"],
        "cards": [
            {"label": "30-Day Forecast", "value": f"₹{total_forecast:,.0f}", "hint": "Projected revenue"},
            {"label": "Daily Average", "value": f"₹{total_forecast/30:,.0f}", "hint": "Expected per day"},
            {"label": "Confidence", "value": "85%", "hint": "Model accuracy"},
            {"label": "Trend", "value": forecast.get("trend", "stable").title(), "hint": "Direction"}
        ],
        "charts": [
            {
                "title": "Revenue Forecast (Next 30 Days)",
                "type": "line",
                "labels": dates,
                "datasets": [
                    {"label": "Forecast", "data": predictions, "borderColor": "#10b981", "fill": False},
                    {"label": "Upper Bound", "data": upper, "borderColor": "rgba(16, 185, 129, 0.3)", "borderDash": [5, 5], "fill": False},
                    {"label": "Lower Bound", "data": lower, "borderColor": "rgba(16, 185, 129, 0.3)", "borderDash": [5, 5], "fill": False}
                ]
            }
        ],
        "tables": [
            {
                "title": "Forecast Summary",
                "headers": ["Period", "Forecast", "Lower", "Upper"],
                "rows": [
                    ["Week 1", f"₹{sum(predictions[:7]):,.0f}", f"₹{sum(lower[:7]):,.0f}", f"₹{sum(upper[:7]):,.0f}"],
                    ["Week 2", f"₹{sum(predictions[7:14]):,.0f}", f"₹{sum(lower[7:14]):,.0f}", f"₹{sum(upper[7:14]):,.0f}"],
                    ["Week 3", f"₹{sum(predictions[14:21]):,.0f}", f"₹{sum(lower[14:21]):,.0f}", f"₹{sum(upper[14:21]):,.0f}"],
                    ["Week 4", f"₹{sum(predictions[21:]):,.0f}", f"₹{sum(lower[21:]):,.0f}", f"₹{sum(upper[21:]):,.0f}"]
                ]
            }
        ],
        "insights": [
            f"Forecasted revenue: ₹{total_forecast:,.0f} (next 30 days)",
            f"Trend direction: {forecast.get('trend', 'stable')}",
            f"Confidence level: {forecast.get('confidence_intervals', {}).get('average', 0):.0f}%",
            "Based on Prophet time-series forecasting model"
        ],
        "generated_at": datetime.utcnow().isoformat()
    }


def _get_anomaly_data(db: Session):
    """Get anomaly detection dashboard data"""
    from app.services.anomaly_detection_service import anomaly_detection_service
    
    order_anomalies = anomaly_detection_service.detect_order_anomalies(db)
    inventory_anomalies = anomaly_detection_service.detect_inventory_anomalies(db)
    
    all_anomalies = order_anomalies.get("anomalies", []) + inventory_anomalies.get("anomalies", [])
    high_severity = [a for a in all_anomalies if a.get("severity") == "high"]
    
    # Severity distribution for pie chart
    severity_counts = {"High": len([a for a in all_anomalies if a.get("severity") == "high"]),
                       "Medium": len([a for a in all_anomalies if a.get("severity") == "medium"]),
                       "Low": len([a for a in all_anomalies if a.get("severity") == "low"])}
    
    return {
        "id": "anomaly_detection",
        "name": "Anomaly Detection",
        "description": "Fraud detection and unusual pattern analysis",
        "pages": ["Overview", "Fraud Patterns", "Transaction Anomalies", "User Behavior"],
        "cards": [
            {"label": "Total Anomalies", "value": f"{len(all_anomalies)}", "hint": "Detected today"},
            {"label": "High Severity", "value": f"{len(high_severity)}", "hint": "Requires attention"},
            {"label": "Order Issues", "value": f"{len(order_anomalies.get('anomalies', []))}", "hint": "Order anomalies"},
            {"label": "Inventory Alerts", "value": f"{len(inventory_anomalies.get('anomalies', []))}", "hint": "Stock issues"}
        ],
        "charts": [
            {
                "title": "Anomaly Severity Distribution",
                "type": "doughnut",
                "labels": list(severity_counts.keys()),
                "datasets": [{"data": list(severity_counts.values()), 
                              "backgroundColor": ["#ef4444", "#f59e0b", "#3b82f6"]}]
            }
        ],
        "tables": [
            {
                "title": "Recent Anomalies",
                "headers": ["Type", "Severity", "Description", "Detected"],
                "rows": [[a.get("type", "Unknown"), a.get("severity", "low"), 
                         a.get("message", "")[:50], 
                         a.get("detected_at", "")[:10]] for a in all_anomalies[:10]]
            }
        ],
        "insights": [
            f"{len(high_severity)} high severity anomalies detected",
            f"{len(order_anomalies.get('anomalies', []))} order-related issues",
            f"{len(inventory_anomalies.get('anomalies', []))} inventory alerts",
            "Review flagged transactions for potential fraud"
        ],
        "generated_at": datetime.utcnow().isoformat()
    }


def _get_customer_insights_data(db: Session):
    """Get customer insights dashboard data"""
    from app.services.customer_segmentation_service import customer_segmentation_service
    from app.services.behavior_analysis_service import behavior_analysis_service
    
    segments = customer_segmentation_service.segment_customers(db)
    behavior = behavior_analysis_service.analyze_user_behavior(db)
    
    segment_data = segments.get("segments", {})
    
    # Prepare segment chart data
    segment_names = list(segment_data.keys())
    segment_counts = [s.get("count", 0) for s in segment_data.values()]
    
    return {
        "id": "customer_insights",
        "name": "Customer Insights",
        "description": "Customer segmentation and behavior analysis",
        "pages": ["Segments", "Retention", "Lifetime Value", "Churn Risk"],
        "cards": [
            {"label": "Total Customers", "value": f"{segments.get('total_customers', 0):,}", "hint": "All time"},
            {"label": "VIP Customers", "value": f"{segment_data.get('vip', {}).get('count', 0)}", "hint": "Top tier"},
            {"label": "At Risk", "value": f"{segment_data.get('at_risk', {}).get('count', 0)}", "hint": "Need attention"},
            {"label": "New Customers", "value": f"{segment_data.get('new', {}).get('count', 0)}", "hint": "This month"}
        ],
        "charts": [
            {
                "title": "Customer Segments",
                "type": "doughnut",
                "labels": segment_names,
                "datasets": [{"data": segment_counts, 
                              "backgroundColor": ["#8b5cf6", "#10b981", "#f59e0b", "#ef4444", "#3b82f6"]}]
            }
        ],
        "tables": [
            {
                "title": "Segment Summary",
                "headers": ["Segment", "Count", "Avg Spend", "Risk"],
                "rows": [[name, s.get("count", 0), f"₹{s.get('avg_spend', 0):,.0f}", s.get("risk_level", "low")] 
                         for name, s in segment_data.items()]
            }
        ],
        "insights": [
            f"Total customers segmented: {segments.get('total_customers', 0):,}",
            f"VIP segment: {segment_data.get('vip', {}).get('count', 0)} high-value customers",
            f"At-risk customers: {segment_data.get('at_risk', {}).get('count', 0)}",
            "Focus retention efforts on at-risk segment"
        ],
        "generated_at": datetime.utcnow().isoformat()
    }


def _get_inventory_analytics_data(db: Session, admin_service):
    """Get inventory analytics dashboard data"""
    inventory_trends = admin_service.get_inventory_trends(db)
    low_stock = admin_service.get_low_stock_alerts(db, threshold=10)
    
    categories = [i["category"] for i in inventory_trends]
    stocks = [i["total_stock"] for i in inventory_trends]
    
    return {
        "id": "inventory_analytics",
        "name": "Inventory Analytics",
        "description": "Stock levels, turnover, and warehouse metrics",
        "pages": ["Stock Overview", "Turnover", "Shortage Predictions", "Warehouse"],
        "cards": [
            {"label": "Total Products", "value": f"{sum(i['total_products'] for i in inventory_trends)}", "hint": "In catalog"},
            {"label": "Low Stock Items", "value": f"{len(low_stock)}", "hint": "Below threshold"},
            {"label": "Out of Stock", "value": f"{len([p for p in low_stock if p['stock'] == 0])}", "hint": "Critical"},
            {"label": "Categories", "value": f"{len(inventory_trends)}", "hint": "Active"}
        ],
        "charts": [
            {
                "title": "Inventory by Category",
                "type": "bar",
                "labels": categories,
                "datasets": [{"label": "Stock Units", "data": stocks, "backgroundColor": "#f59e0b"}]
            }
        ],
        "tables": [
            {
                "title": "Low Stock Alerts",
                "headers": ["Product", "Category", "Stock", "Severity"],
                "rows": [[p["name"], p["category"], p["stock"], p["severity"]] for p in low_stock[:10]]
            }
        ],
        "insights": [
            f"{len(low_stock)} products below stock threshold",
            f"{len([p for p in low_stock if p['stock'] == 0])} products out of stock",
            f"{len(inventory_trends)} active categories",
            "Review low stock items for reordering"
        ],
        "generated_at": datetime.utcnow().isoformat()
    }


def _get_agent_analytics_data(db: Session):
    """Get AI agent analytics dashboard data"""
    from app.services.ai_multi_agent_service import ai_multi_agent_center
    
    try:
        agent_status = ai_multi_agent_center.get_agent_status()
        
        agents = list(agent_status.keys())
        health_scores = [agent_status.get(a, {}).get("health_score", 0) for a in agents]
        
        return {
            "id": "agent_analytics",
            "name": "AI Agent Analytics",
            "description": "Multi-agent system performance and health",
            "pages": ["Overview", "Task Execution", "Agent Health", "Orchestration"],
            "cards": [
                {"label": "Active Agents", "value": f"{len(agents)}", "hint": "Running"},
                {"label": "Avg Health", "value": f"{sum(health_scores)/len(health_scores):.0f}%", "hint": "System health"},
                {"label": "Tasks Today", "value": "N/A", "hint": "Executed"},
                {"label": "Orchestrator", "value": "Active", "hint": "Status"}
            ],
            "charts": [
                {
                    "title": "Agent Health Scores",
                    "type": "bar",
                    "labels": agents,
                    "datasets": [{"label": "Health %", "data": health_scores, "backgroundColor": "#06b6d4"}]
                }
            ],
            "tables": [
                {
                    "title": "Agent Status",
                    "headers": ["Agent", "Status", "Health", "Tasks"],
                    "rows": [[name, s.get("status", "unknown"), f"{s.get('health_score', 0)}%", s.get("tasks_completed", 0)] 
                             for name, s in agent_status.items()]
                }
            ],
            "insights": [
                f"{len(agents)} AI agents active",
                f"Average health score: {sum(health_scores)/len(health_scores):.0f}%" if health_scores else "No health data",
                "Multi-agent orchestration running",
                "All agents operational"
            ],
            "generated_at": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "id": "agent_analytics",
            "name": "AI Agent Analytics",
            "description": "Multi-agent system performance and health",
            "pages": ["Overview", "Task Execution", "Agent Health", "Orchestration"],
            "cards": [
                {"label": "Active Agents", "value": "4", "hint": "Running"},
                {"label": "System", "value": "Online", "hint": "Status"}
            ],
            "charts": [],
            "tables": [],
            "insights": ["Agent analytics temporarily unavailable", f"Error: {str(e)}"],
            "generated_at": datetime.utcnow().isoformat()
        }


def _get_default_dashboard_data(db: Session, dashboard_config):
    """Get default dashboard data"""
    return {
        "id": dashboard_config["id"],
        "name": dashboard_config["name"],
        "description": dashboard_config["description"],
        "pages": dashboard_config.get("pages", []),
        "cards": [{"label": "Status", "value": "Active", "hint": "Dashboard ready"}],
        "charts": [],
        "tables": [],
        "insights": ["Dashboard loaded successfully"],
        "generated_at": datetime.utcnow().isoformat()
    }


@router.get("/api/admin/powerbi/export")
def export_powerbi_data(request: Request, dataset: str = "all", db: Session = Depends(get_db)):
    """Export data for Power BI import"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    if dataset == "all":
        data = powerbi_service.get_all_powerbi_datasets(db)
    elif dataset == "sales":
        data = {"sales_data": powerbi_service.export_sales_data(db)}
    elif dataset == "customers":
        data = {"customer_data": powerbi_service.export_customer_data(db)}
    elif dataset == "inventory":
        data = {"inventory_data": powerbi_service.export_inventory_data(db)}
    elif dataset == "tickets":
        data = {"support_tickets": powerbi_service.export_support_tickets_data(db)}
    elif dataset == "metrics":
        data = {"daily_metrics": powerbi_service.export_daily_metrics(db)}
    else:
        raise HTTPException(status_code=400, detail=f"Unknown dataset: {dataset}")
    
    return JSONResponse(data)


@router.get("/api/admin/powerbi/metrics")
def get_powerbi_key_metrics(request: Request, db: Session = Depends(get_db)):
    """Get key metrics for Power BI dashboard"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    metrics = powerbi_service.get_key_metrics(db)
    return JSONResponse(metrics)


@router.get("/api/admin/powerbi/model-outputs")
def get_powerbi_model_outputs(request: Request, db: Session = Depends(get_db)):
    """Get AI model outputs for Power BI"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    outputs = powerbi_service.get_model_outputs(db)
    return JSONResponse(outputs)


@router.get("/api/admin/powerbi/anomalies")
def get_powerbi_anomalies(request: Request, db: Session = Depends(get_db)):
    """Get anomaly alerts and trends for Power BI"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    anomalies = powerbi_service.get_anomaly_alerts_and_trends(db)
    return JSONResponse(anomalies)


@router.get("/api/admin/powerbi/insights")
def get_powerbi_insights(request: Request, db: Session = Depends(get_db)):
    """Get AI agent-driven insights for Power BI"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    insights = powerbi_service.get_agent_driven_insights(db)
    return JSONResponse(insights)


@router.get("/api/admin/powerbi/config")
def get_powerbi_config(request: Request, db: Session = Depends(get_db)):
    """Get Power BI configuration and status"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from app.config import settings
    
    return JSONResponse({
        "enabled": settings.powerbi_enabled,
        "workspace_id": settings.azure_powerbi_workspace_id or powerbi_service.workspace_id,
        "azure_configured": all([
            settings.azure_tenant_id,
            settings.azure_client_id,
            settings.azure_client_secret
        ]),
        "dashboards_count": len(powerbi_service.dashboards),
        "dashboards": powerbi_service.get_all_dashboards(),
        "embed_config": powerbi_service.get_comprehensive_analytics().get("embed_config", {})
    })


# ==================== Data Pipeline API Routes ====================

@router.get("/api/admin/pipeline/status")
def get_pipeline_status(request: Request, db: Session = Depends(get_db)):
    """Get real-time data pipeline status and configuration"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from app.config import settings
    from app.services.data_pipeline_service import (
        local_pipeline_service, 
        get_pipeline_status as get_rt_status,
        realtime_manager
    )
    
    rt_status = get_rt_status()
    
    return JSONResponse({
        "enabled": settings.data_pipeline_enabled,
        "azure_configured": all([
            settings.azure_storage_account,
            settings.azure_subscription_id,
            settings.azure_resource_group
        ]),
        "real_time": {
            "is_running": rt_status["is_running"],
            "last_run": rt_status["last_run"],
            "cache_age_seconds": rt_status["cache_age_seconds"],
            "has_cached_data": rt_status["has_cached_data"],
            "refresh_interval_minutes": rt_status["refresh_interval_minutes"],
            "scheduler_active": rt_status["scheduler_active"]
        },
        "storage_account": settings.azure_storage_account,
        "adf_factory": settings.adf_factory_name,
        "layers": {
            "raw": local_pipeline_service.raw_path,
            "staging": local_pipeline_service.staging_path,
            "curated": local_pipeline_service.curated_path
        },
        "is_real_data": True
    })


@router.post("/api/admin/pipeline/run")
def run_data_pipeline(request: Request, force: bool = False, db: Session = Depends(get_db)):
    """Trigger data pipeline execution with real-time updates"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from app.services.data_pipeline_service import realtime_manager
    from datetime import datetime
    
    try:
        # Use real-time manager - force=True to bypass cache
        result = realtime_manager.get_data(db, force_refresh=force)
        
        return JSONResponse({
            "success": True,
            "execution_id": result["execution_id"],
            "status": result["status"],
            "duration_seconds": result["duration_seconds"],
            "records_processed": result["layers"]["curated"]["total_records"],
            "layers": result["layers"],
            "source": "sqlite_real_data",
            "is_real_time": True,
            "timestamp": datetime.utcnow().isoformat()
        })
    except Exception as e:
        logger.error(f"Pipeline execution failed: {e}")
        return JSONResponse({
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }, status_code=500)


@router.post("/api/admin/pipeline/scheduler/{action}")
def control_scheduler(action: str, request: Request, db: Session = Depends(get_db)):
    """Start or stop the real-time pipeline scheduler"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from app.services.data_pipeline_service import (
        start_realtime_pipeline, 
        stop_realtime_pipeline,
        get_pipeline_status
    )
    from app.database import SessionLocal
    
    if action == "start":
        start_realtime_pipeline(SessionLocal)
        return JSONResponse({
            "success": True,
            "message": "Real-time scheduler started",
            "status": get_pipeline_status()
        })
    elif action == "stop":
        stop_realtime_pipeline()
        return JSONResponse({
            "success": True,
            "message": "Real-time scheduler stopped",
            "status": get_pipeline_status()
        })
    else:
        raise HTTPException(status_code=400, detail="Invalid action. Use 'start' or 'stop'")


@router.get("/api/admin/pipeline/data")
def get_pipeline_data(request: Request, layer: str = "curated", db: Session = Depends(get_db)):
    """Get data from pipeline layers (raw, staging, curated)"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from app.services.data_pipeline_service import local_pipeline_service
    
    # Run pipeline to get fresh data
    result = local_pipeline_service.run_full_pipeline(db)
    
    if layer == "curated":
        data = result.get("data", {})
    elif layer == "staging":
        # Extract staging data from pipeline
        data = local_pipeline_service.transform_to_staging(
            local_pipeline_service.extract_raw_data(db)
        )
    elif layer == "raw":
        data = local_pipeline_service.extract_raw_data(db)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown layer: {layer}")
    
    # Limit data size for API response
    for key in data:
        if isinstance(data[key], list) and len(data[key]) > 100:
            data[key] = data[key][:100]
            data[f"{key}_truncated"] = True
    
    return JSONResponse({
        "layer": layer,
        "execution_id": result["execution_id"],
        "data": data,
        "timestamp": datetime.utcnow().isoformat()
    })


@router.get("/api/admin/pipeline/quality")
def get_pipeline_quality(request: Request, db: Session = Depends(get_db)):
    """Get data quality report from pipeline"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from app.services.data_pipeline_service import local_pipeline_service
    
    # Run pipeline and get quality report
    result = local_pipeline_service.run_full_pipeline(db)
    quality_report = local_pipeline_service.get_data_quality_report(result.get("data", {}))
    
    return JSONResponse({
        "execution_id": result["execution_id"],
        "execution_date": quality_report.execution_date,
        "quality_score": quality_report.quality_score,
        "status": quality_report.status,
        "total_checks": quality_report.total_checks,
        "passed_checks": quality_report.passed_checks,
        "failed_checks": quality_report.failed_checks,
        "critical_failures": quality_report.critical_failures,
        "timestamp": datetime.utcnow().isoformat()
    })


@router.get("/api/admin/pipeline/layers/{layer_name}/tables")
def get_pipeline_tables(layer_name: str, request: Request, db: Session = Depends(get_db)):
    """Get list of tables in a specific pipeline layer"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    layer_tables = {
        "raw": ["users", "products", "orders", "order_items", "support_tickets", "cart_items", "wishlist_items"],
        "staging": ["dim_customers", "dim_products", "fact_orders", "fact_order_items", "fact_support_tickets"],
        "curated": ["sales_daily", "sales_weekly", "sales_monthly", "customer_360", 
                    "inventory_analytics", "anomaly_features", "product_performance"]
    }
    
    if layer_name not in layer_tables:
        raise HTTPException(status_code=400, detail=f"Unknown layer: {layer_name}")
    
    return JSONResponse({
        "layer": layer_name,
        "tables": layer_tables[layer_name],
        "count": len(layer_tables[layer_name])
    })


@router.get("/api/admin/pipeline/dashboard")
def get_pipeline_dashboard_data(request: Request, db: Session = Depends(get_db)):
    """Get consolidated pipeline data for dashboard display"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from app.services.data_pipeline_service import local_pipeline_service
    
    # Run pipeline to get all data
    result = local_pipeline_service.run_full_pipeline(db)
    curated = result.get("data", {})
    quality = local_pipeline_service.get_data_quality_report(curated)
    
    # Calculate key metrics
    sales_daily = curated.get("sales_daily", [])
    customer_360 = curated.get("customer_360", [])
    inventory = curated.get("inventory_analytics", [])
    anomalies = curated.get("anomaly_features", [])
    
    total_revenue = sum(d.get("total_revenue", 0) for d in sales_daily)
    total_orders = sum(d.get("total_orders", 0) for d in sales_daily)
    avg_order_value = total_revenue / total_orders if total_orders > 0 else 0
    
    vip_customers = sum(1 for c in customer_360 if c.get("rfm_segment") == "Champions")
    at_risk_customers = sum(1 for c in customer_360 if c.get("churn_risk_segment") == "High Risk")
    
    critical_stock = sum(1 for i in inventory if i.get("stock_status") in ["Out of Stock", "Low Stock"])
    reorder_needed = sum(1 for i in inventory if i.get("reorder_recommended"))
    
    detected_anomalies = sum(1 for a in anomalies if a.get("is_anomaly"))
    
    return JSONResponse({
        "execution_id": result["execution_id"],
        "execution_timestamp": result["end_time"],
        "quality": {
            "score": quality.quality_score,
            "status": quality.status,
            "checks_passed": quality.passed_checks,
            "checks_total": quality.total_checks
        },
        "metrics": {
            "total_revenue": round(total_revenue, 2),
            "total_orders": total_orders,
            "avg_order_value": round(avg_order_value, 2),
            "active_customers": len(customer_360),
            "vip_customers": vip_customers,
            "at_risk_customers": at_risk_customers,
            "products_critical_stock": critical_stock,
            "products_reorder_needed": reorder_needed,
            "anomalies_detected": detected_anomalies
        },
        "layers": result["layers"],
        "data_samples": {
            "sales_daily": sales_daily[:7] if sales_daily else [],
            "customer_segments": {}
        }
    })


@router.get("/admin/data-pipeline", response_class=HTMLResponse)
def data_pipeline_page(request: Request, db: Session = Depends(get_db)):
    """Data Pipeline admin page - Azure Data Engineering"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    return templates.TemplateResponse(
        "admin/data_pipeline.html",
        {
            "request": request,
            "user": user
        }
    )


@router.get("/pipeline/analytics")
def pipeline_analytics(request: Request, mode: str = "dynamic", db: Session = Depends(get_db)):
    """Get real-time analytics from live database pipeline or CSV (static mode)."""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        if mode == "static":
            # Use CSV pipeline service for static mode
            from app.services.csv_pipeline_service import get_analytics_payload, get_layer_payload
            payload = get_analytics_payload()
            return JSONResponse({
                "summary": {
                    "total_revenue": payload["summary"]["total_revenue"],
                    "total_orders": payload["summary"]["total_orders"],
                    "avg_order_value": payload["summary"]["avg_order_value"],
                    "records": payload["summary"]["records"],
                    "period_start": payload["summary"]["period_start"],
                    "period_end": payload["summary"]["period_end"]
                },
                "layer_counts": payload["layer_counts"],
                "quality": payload["quality"],
                "trend": payload["trend"],
                "anomalies": payload["anomalies"],
                "timestamp": payload["timestamp"]
            })
        else:
            # Use database pipeline service for dynamic mode
            from app.services.data_pipeline_service import local_pipeline_service
            result = local_pipeline_service.run_full_pipeline(db)
            curated = result.get("data", {})
            quality = local_pipeline_service.get_data_quality_report(curated)
            
            # Build trend from daily sales
            trend = []
            for item in curated.get("sales_daily", []):
                trend.append({
                    "date": item.get("created_at"),
                    "revenue": item.get("total_revenue", 0),
                    "orders": item.get("total_orders", 0)
                })
            
            return JSONResponse({
                "summary": {
                    "total_revenue": sum(s.get("total_revenue", 0) for s in curated.get("sales_daily", [])),
                    "total_orders": sum(s.get("total_orders", 0) for s in curated.get("sales_daily", [])),
                    "avg_order_value": (sum(s.get("total_revenue", 0) for s in curated.get("sales_daily", [])) / max(sum(s.get("total_orders", 0) for s in curated.get("sales_daily", [])), 1)),
                    "records": result["layers"]["curated"]["total_records"]
                },
                "layer_counts": result.get("layers", {}),
                "quality": {
                    "overall_score": quality.quality_score,
                    "total_checks": quality.total_checks,
                    "passed_checks": quality.passed_checks,
                    "failed_checks": quality.failed_checks,
                    "status": quality.status
                },
                "trend": trend,
                "anomalies": curated.get("anomaly_features", []),
                "timestamp": datetime.utcnow().isoformat()
            })
    except Exception as error:
        logger.error(f"Pipeline analytics failed: {error}")
        raise HTTPException(status_code=500, detail=str(error))


@router.get("/pipeline/bronze")
def pipeline_bronze(request: Request, table: str | None = None, mode: str = "dynamic", db: Session = Depends(get_db)):
    """Return Bronze layer (raw extracted data) from live database or CSV."""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        if mode == "static":
            # Use CSV pipeline service for static mode
            from app.services.csv_pipeline_service import get_layer_payload
            payload = get_layer_payload("bronze", table)
            return JSONResponse(payload)
        else:
            # Use database pipeline service for dynamic mode
            from app.services.data_pipeline_service import local_pipeline_service
            raw_data = local_pipeline_service.extract_raw_data(db)
            
            if not table:
                return JSONResponse({"layer": "bronze", "tables": list(raw_data.keys())})
            
            if table not in raw_data:
                raise HTTPException(status_code=400, detail=f"Unknown table: {table}")
            
            records = raw_data[table] if isinstance(raw_data[table], list) else []
            return JSONResponse({"layer": "bronze", "table": table, "records": records})
    except Exception as error:
        logger.error(f"Pipeline bronze failed: {error}")
        raise HTTPException(status_code=500, detail=str(error))


@router.get("/pipeline/silver")
def pipeline_silver(request: Request, table: str | None = None, mode: str = "dynamic", db: Session = Depends(get_db)):
    """Return Silver layer (transformed staging data) from live database or CSV."""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        if mode == "static":
            # Use CSV pipeline service for static mode
            from app.services.csv_pipeline_service import get_layer_payload
            payload = get_layer_payload("silver", table)
            return JSONResponse(payload)
        else:
            # Use database pipeline service for dynamic mode
            from app.services.data_pipeline_service import local_pipeline_service
            raw_data = local_pipeline_service.extract_raw_data(db)
            staging_data = local_pipeline_service.transform_to_staging(raw_data)
            
            if not table:
                return JSONResponse({"layer": "silver", "tables": list(staging_data.keys())})
            
            if table not in staging_data:
                raise HTTPException(status_code=400, detail=f"Unknown table: {table}")
            
            records = staging_data[table] if isinstance(staging_data[table], list) else []
            return JSONResponse({"layer": "silver", "table": table, "records": records})
    except Exception as error:
        logger.error(f"Pipeline silver failed: {error}")
        raise HTTPException(status_code=500, detail=str(error))


@router.get("/pipeline/gold")
def pipeline_gold(request: Request, table: str | None = None, mode: str = "dynamic", db: Session = Depends(get_db)):
    """Return Gold layer (curated analytics) from live database or CSV."""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        if mode == "static":
            # Use CSV pipeline service for static mode
            from app.services.csv_pipeline_service import get_layer_payload
            payload = get_layer_payload("gold", table)
            return JSONResponse(payload)
        else:
            # Use database pipeline service for dynamic mode
            from app.services.data_pipeline_service import local_pipeline_service
            result = local_pipeline_service.run_full_pipeline(db)
            curated_data = result.get("data", {})
            
            if not table:
                return JSONResponse({"layer": "gold", "tables": list(curated_data.keys())})
            
            if table not in curated_data:
                raise HTTPException(status_code=400, detail=f"Unknown table: {table}")
            
            records = curated_data[table] if isinstance(curated_data[table], list) else []
            return JSONResponse({"layer": "gold", "table": table, "records": records})
    except Exception as error:
        logger.error(f"Pipeline gold failed: {error}")
        raise HTTPException(status_code=500, detail=str(error))


@router.get("/admin/sentiment-analytics", response_class=HTMLResponse)
def admin_sentiment_analytics_page(request: Request, db: Session = Depends(get_db)):
    """Admin Sentiment Analytics page - Azure AI Language Text Analytics"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        return RedirectResponse(url="/login", status_code=302)
    
    return templates.TemplateResponse(
        "admin_sentiment_analytics.html",
        {
            "request": request,
            "user": user
        }
    )


# ==================== Review & Sentiment Analysis API Routes ====================

from pydantic import BaseModel, Field, validator

class ReviewCreateRequest(BaseModel):
    """Request model for creating a review"""
    order_id: int = Field(..., description="Order ID")
    product_id: int = Field(..., description="Product ID")
    review_text: str = Field(..., min_length=5, max_length=1000, description="Review text")
    rating: int = Field(..., ge=1, le=5, description="Rating from 1-5 stars")
    
    @validator('review_text')
    def validate_review_text(cls, v):
        if not v or len(v.strip()) < 5:
            raise ValueError('Review text must be at least 5 characters')
        if len(v) > 1000:
            raise ValueError('Review text must not exceed 1000 characters')
        return v.strip()


@router.post("/api/v1/reviews")
async def create_review(
    request: Request,
    review_data: ReviewCreateRequest,
    db: Session = Depends(get_db)
):
    """
    Create a new review with Azure AI Language sentiment analysis.
    
    Requirements:
    - User must be authenticated
    - Order must belong to the user
    - Order status must be "Delivered"
    - No duplicate reviews allowed for same order/product/user
    """
    # Get current user
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Import review service
    from app.services.review_service import review_service
    
    try:
        # Step 1: Validate order belongs to user and is delivered
        order = db.query(Order).filter(
            Order.id == review_data.order_id,
            Order.user_id == user.id
        ).first()
        
        if not order:
            logger.warning(f"Review attempt for invalid order: user={user.id}, order={review_data.order_id}")
            raise HTTPException(
                status_code=403, 
                detail="Order not found or does not belong to you"
            )
        
        # Step 2: Validate order status is "Delivered"
        if order.status != "Delivered":
            logger.warning(f"Review attempt for non-delivered order: user={user.id}, order={review_data.order_id}, status={order.status}")
            raise HTTPException(
                status_code=400, 
                detail=f"Cannot review order with status '{order.status}'. Only delivered orders can be reviewed."
            )
        
        # Step 3: Validate product exists in the order
        order_item = db.query(OrderItem).filter(
            OrderItem.order_id == review_data.order_id,
            OrderItem.product_id == review_data.product_id
        ).first()
        
        if not order_item:
            logger.warning(f"Review attempt for product not in order: user={user.id}, order={review_data.order_id}, product={review_data.product_id}")
            raise HTTPException(
                status_code=400, 
                detail="This product was not purchased in the specified order"
            )
        
        # Step 4: Check for duplicate review
        if review_service.has_user_reviewed(user.id, review_data.order_id, review_data.product_id):
            logger.warning(f"Duplicate review attempt: user={user.id}, order={review_data.order_id}, product={review_data.product_id}")
            raise HTTPException(
                status_code=409, 
                detail="You have already reviewed this product for this order"
            )
        
        # Step 5: Get product name for storage
        product = db.query(Product).filter(Product.id == review_data.product_id).first()
        product_name = product.name if product else "Unknown Product"
        
        # Step 6: Create review with Azure sentiment analysis
        result = review_service.create_review(
            user_id=user.id,
            order_id=review_data.order_id,
            product_id=review_data.product_id,
            review_text=review_data.review_text,
            rating=review_data.rating,
            user_name=user.name,
            product_name=product_name
        )
        
        if not result["success"]:
            logger.error(f"Failed to create review: {result.get('error')}")
            raise HTTPException(status_code=500, detail=result.get("error", "Failed to create review"))
        
        # Log successful review creation
        logger.info(f"Review created successfully: user={user.id}, order={review_data.order_id}, product={review_data.product_id}, sentiment={result['review']['sentiment']}")
        
        # Log user activity
        review_activity = (
            f"Sentiment: {result['review']['sentiment']} | "
            f"Rating: {review_data.rating}/5 | "
            f"Product: {product_name} | "
            f"Order: #{order.order_number} | "
            f"Review: {review_data.review_text}"
        )
        log_user_activity(user.id, "review", db, review_activity)
        
        return JSONResponse({
            "success": True,
            "message": "Review submitted successfully",
            "review": result["review"]
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error creating review: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/api/v1/reviews/check")
def check_review_eligibility(
    request: Request,
    order_id: int,
    product_id: int,
    db: Session = Depends(get_db)
):
    """
    Check if user can submit a review for a specific order/product.
    Returns eligibility status and any existing review.
    """
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    from app.services.review_service import review_service
    
    # Check order exists and belongs to user
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == user.id
    ).first()
    
    if not order:
        return JSONResponse({
            "eligible": False,
            "reason": "Order not found",
            "can_review": False
        })
    
    # Check order is delivered
    if order.status != "Delivered":
        return JSONResponse({
            "eligible": False,
            "reason": f"Order status is '{order.status}'. Only delivered orders can be reviewed.",
            "order_status": order.status,
            "can_review": False
        })
    
    # Check product in order
    order_item = db.query(OrderItem).filter(
        OrderItem.order_id == order_id,
        OrderItem.product_id == product_id
    ).first()
    
    if not order_item:
        return JSONResponse({
            "eligible": False,
            "reason": "Product not found in this order",
            "can_review": False
        })
    
    # Check for existing review
    has_reviewed = review_service.has_user_reviewed(user.id, order_id, product_id)
    
    if has_reviewed:
        return JSONResponse({
            "eligible": False,
            "reason": "You have already reviewed this product",
            "can_review": False,
            "already_reviewed": True
        })
    
    return JSONResponse({
        "eligible": True,
        "reason": None,
        "order_status": order.status,
        "can_review": True,
        "already_reviewed": False
    })


@router.get("/api/v1/reviews/order/{order_id}")
def get_order_reviews(
    order_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Get all reviews for a specific order (for the order owner)"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Verify order belongs to user
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == user.id
    ).first()
    
    if not order:
        raise HTTPException(status_code=403, detail="Order not found")
    
    from app.services.review_service import review_service
    reviews = review_service.get_reviews_by_order(order_id)
    
    return JSONResponse({
        "order_id": order_id,
        "reviews": reviews,
        "count": len(reviews)
    })


@router.get("/api/v1/reviews/product/{product_id}")
def get_product_reviews(product_id: int, limit: int = 50):
    """Get all public reviews for a product"""
    from app.services.review_service import review_service
    
    reviews = review_service.get_reviews_by_product(product_id, limit)
    
    # Calculate average rating and sentiment distribution
    if reviews:
        avg_rating = sum(r.get("rating", 0) for r in reviews) / len(reviews)
        sentiment_dist = {}
        for r in reviews:
            sentiment = r.get("sentiment", "neutral")
            sentiment_dist[sentiment] = sentiment_dist.get(sentiment, 0) + 1
    else:
        avg_rating = 0
        sentiment_dist = {}
    
    return JSONResponse({
        "product_id": product_id,
        "reviews": reviews,
        "count": len(reviews),
        "average_rating": round(avg_rating, 1) if reviews else None,
        "sentiment_distribution": sentiment_dist
    })


@router.get("/api/admin/azure-language/status")
def get_azure_language_status(request: Request, db: Session = Depends(get_db)):
    """Get Azure AI Language service status for debugging"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from app.services.azure_text_analytics import azure_text_analytics
    from app.config import settings
    
    # Build troubleshooting messages
    issues = []
    if not settings.azure_language_enabled:
        issues.append("AZURE_LANGUAGE_ENABLED is not set to 'true' in .env file")
    if not settings.azure_language_endpoint:
        issues.append("AZURE_LANGUAGE_ENDPOINT is missing in .env file")
    if not settings.azure_language_key:
        issues.append("AZURE_LANGUAGE_KEY is missing in .env file")
    
    # Check endpoint format
    endpoint_valid = True
    if settings.azure_language_endpoint:
        if not settings.azure_language_endpoint.startswith("https://"):
            issues.append("AZURE_LANGUAGE_ENDPOINT should start with https://")
            endpoint_valid = False
        if not settings.azure_language_endpoint.endswith(".azure.com") and not settings.azure_language_endpoint.endswith("/"):
            issues.append("AZURE_LANGUAGE_ENDPOINT format looks incorrect - should be like: https://your-resource.cognitiveservices.azure.com/")
    
    # Test actual connection by analyzing a sample text
    test_result = None
    if azure_text_analytics.enabled:
        try:
            test_sentiment = azure_text_analytics.analyze_sentiment("This is a great product! I love it.")
            test_result = {
                "success": test_sentiment.success,
                "sentiment": test_sentiment.sentiment,
                "confidence": test_sentiment.confidence_scores,
                "error": test_sentiment.error_message
            }
        except Exception as e:
            test_result = {"success": False, "error": str(e)}
            issues.append(f"API test failed: {str(e)}")
    
    return JSONResponse({
        "service_status": azure_text_analytics.get_service_status(),
        "config_loaded": {
            "endpoint": bool(settings.azure_language_endpoint),
            "key": bool(settings.azure_language_key),
            "enabled": settings.azure_language_enabled,
            "endpoint_valid": endpoint_valid
        },
        "endpoint_preview": settings.azure_language_endpoint[:40] + "..." if settings.azure_language_endpoint else None,
        "test_analysis": test_result,
        "issues": issues,
        "troubleshooting_steps": [
            "1. Check .env file has: AZURE_LANGUAGE_ENABLED=true",
            "2. Verify endpoint format: https://your-resource.cognitiveservices.azure.com/",
            "3. Ensure key is correct from Azure Portal > Keys and Endpoint",
            "4. Restart server after changing .env file",
            "5. Check server logs for detailed error messages"
        ]
    })


@router.get("/api/admin/sentiment-analytics")
def get_sentiment_analytics(request: Request, db: Session = Depends(get_db)):
    """
    Get sentiment analytics for admin dashboard.
    Includes sentiment distribution, trends, and recent reviews.
    """
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from app.services.review_service import review_service
    from app.services.azure_text_analytics import azure_text_analytics
    
    # Get sentiment analytics
    analytics = review_service.get_sentiment_analytics()
    
    # Get recent reviews
    recent_reviews = review_service.get_recent_reviews(limit=20)
    
    # Get service health
    service_health = review_service.get_service_health()
    
    return JSONResponse({
        "analytics": analytics,
        "recent_reviews": recent_reviews,
        "service_health": service_health,
        "timestamp": datetime.utcnow().isoformat()
    })


@router.get("/api/admin/sentiment-reviews/recent")
def get_recent_reviews_for_admin(
    request: Request,
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """Get recent reviews for admin review management"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from app.services.review_service import review_service
    
    reviews = review_service.get_recent_reviews(limit=limit)
    
    return JSONResponse({
        "reviews": reviews,
        "count": len(reviews),
        "timestamp": datetime.utcnow().isoformat()
    })


@router.delete("/api/admin/reviews/{review_id}")
def delete_review_admin(
    review_id: str,
    request: Request,
    db: Session = Depends(get_db)
):
    """Delete a review (admin only)"""
    user = get_current_user(request, db)
    if not user or not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from app.services.review_service import review_service
    
    # Admin can delete any review (pass user_id as 0 for admin override)
    deleted = review_service.delete_review(review_id, 0)
    
    if deleted:
        logger.info(f"Admin deleted review: {review_id}")
        return JSONResponse({"success": True, "message": "Review deleted successfully"})
    else:
        raise HTTPException(status_code=404, detail="Review not found")


def mount_routes(app: FastAPI):
    app.include_router(router)
