from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from uuid import uuid4
from app.auth import hash_password
from app.config import settings
from app.models import Product, User, Order, OrderItem, UserActivity, AuditLog
from app.services.user_management_service import Role, UserRole


PRODUCTS = [
    {
        "sku": "SH-TS-001", "name": "Classic Black T-Shirt", "category": "T-Shirts",
        "description": "Premium cotton black t-shirt for daily wear.", "price": 799,
        "stock": 35, "image": "https://images.unsplash.com/photo-1521572163474-6864f9cf17ab?q=80&w=800&auto=format&fit=crop", "sizes": "S,M,L,XL"
    },
    {
        "sku": "SH-HD-002", "name": "Urban Grey Hoodie", "category": "Hoodies",
        "description": "Soft fleece hoodie with modern streetwear fit.", "price": 1899,
        "stock": 18, "image": "https://images.unsplash.com/photo-1556821840-3a63f95609a7?q=80&w=800&auto=format&fit=crop", "sizes": "M,L,XL"
    },
    {
        "sku": "SH-JN-003", "name": "Slim Fit Blue Jeans", "category": "Jeans",
        "description": "Stretchable slim-fit jeans with clean finish.", "price": 2199,
        "stock": 22, "image": "https://images.unsplash.com/photo-1541099649105-f69ad21f3246?q=80&w=800&auto=format&fit=crop", "sizes": "30,32,34,36"
    },
    {
        "sku": "SH-JK-004", "name": "Denim Jacket", "category": "Jackets",
        "description": "Versatile denim jacket for every season.", "price": 2499,
        "stock": 16, "image": "https://images.unsplash.com/photo-1512436991641-6745cdb1723f?q=80&w=800&auto=format&fit=crop", "sizes": "M,L,XL"
    },
    {
        "sku": "SH-DR-005", "name": "Floral Summer Dress", "category": "Dresses",
        "description": "Lightweight floral dress for festive and casual outings.", "price": 1799,
        "stock": 27, "image": "https://images.unsplash.com/photo-1496747611176-843222e1e57c?q=80&w=800&auto=format&fit=crop", "sizes": "S,M,L"
    },
    {
        "sku": "SH-SH-006", "name": "White Sneakers", "category": "Footwear",
        "description": "Minimal everyday sneakers with cushioned sole.", "price": 2299,
        "stock": 14, "image": "https://images.unsplash.com/photo-1542291026-7eec264c27ff?q=80&w=800&auto=format&fit=crop", "sizes": "7,8,9,10"
    },
    {
        "sku": "SH-SR-007", "name": "Formal Checked Shirt", "category": "Shirts",
        "description": "Wrinkle-resistant checked shirt for office wear.", "price": 1499,
        "stock": 26, "image": "https://images.unsplash.com/photo-1603252109303-2751441dd157?q=80&w=800&auto=format&fit=crop", "sizes": "M,L,XL"
    },
    {
        "sku": "SH-KR-008", "name": "Ethnic Kurta Set", "category": "Ethnic",
        "description": "Elegant kurta set for festive celebrations.", "price": 2599,
        "stock": 12, "image": "https://images.unsplash.com/photo-1610030469983-98e550d6193c?q=80&w=800&auto=format&fit=crop", "sizes": "S,M,L,XL"
    }
]


SAMPLE_USERS = [
    {"name": "John Smith", "email": "john@example.com", "phone": "9876543210", "is_admin": False},
    {"name": "Sarah Johnson", "email": "sarah@example.com", "phone": "8765432109", "is_admin": False},
    {"name": "Mike Davis", "email": "mike@example.com", "phone": "7654321098", "is_admin": False},
    {"name": "Emily Brown", "email": "emily@example.com", "phone": "6543210987", "is_admin": False},
    {"name": "David Wilson", "email": "david@example.com", "phone": "5432109876", "is_admin": False},
    {"name": "Lisa Anderson", "email": "lisa@example.com", "phone": "4321098765", "is_admin": False},
]

ROLES = [
    {"name": "admin", "permissions": '["users.manage", "orders.manage", "products.manage", "analytics.view"]'},
    {"name": "customer", "permissions": '["orders.create", "profile.edit", "cart.manage"]'},
    {"name": "manager", "permissions": '["orders.manage", "products.view", "analytics.view"]'},
]


def seed_data(db: Session):
    # Create admin user
    admin = db.query(User).filter(User.email == settings.admin_email).first()
    if not admin:
        admin = User(
            name="Admin",
            email=settings.admin_email,
            phone="9999999999",
            password_hash=hash_password(settings.admin_password),
            is_admin=True,
        )
        db.add(admin)
        db.flush()

    # Create sample users
    users = []
    for user_data in SAMPLE_USERS:
        existing = db.query(User).filter(User.email == user_data["email"]).first()
        if not existing:
            user = User(
                name=user_data["name"],
                email=user_data["email"],
                phone=user_data["phone"],
                password_hash=hash_password("password123"),
                is_admin=user_data["is_admin"],
                created_at=datetime.utcnow() - timedelta(days=30)
            )
            db.add(user)
            users.append(user)
    db.flush()
    users = db.query(User).filter(User.is_admin == False).all()

    # Create roles
    roles = {}
    for role_data in ROLES:
        existing = db.query(Role).filter(Role.name == role_data["name"]).first()
        if not existing:
            role = Role(name=role_data["name"], permissions=role_data["permissions"])
            db.add(role)
            db.flush()
            roles[role.name] = role

    # Assign roles to users
    if roles:
        for user in users[:3]:
            existing = db.query(UserRole).filter(
                UserRole.user_id == user.id,
                UserRole.role_id == roles.get("customer", db.query(Role).filter(Role.name == "customer").first()).id
            ).first()
            if not existing and roles.get("customer"):
                db.add(UserRole(user_id=user.id, role_id=roles["customer"].id))

    # Create products
    if db.query(Product).count() == 0:
        for product in PRODUCTS:
            db.add(Product(**product))
        db.flush()

    products = db.query(Product).all()

    # Create sample orders
    if db.query(Order).count() == 0 and users and products:
        order_statuses = ["Delivered", "Shipped", "Processing", "Pending", "Cancelled"]
        for i, user in enumerate(users):
            for j in range(2, 5):
                product = products[(i + j) % len(products)]
                order = Order(
                    user_id=user.id,
                    order_number=f"ORD-{uuid4().hex[:8].upper()}",
                    customer_name=user.name,
                    phone=user.phone,
                    address=f"Address {j}, Street {i}",
                    city="City",
                    state="State",
                    pincode="000000",
                    status=order_statuses[j % len(order_statuses)],
                    tracking_id=f"TRK-{uuid4().hex[:10].upper()}",
                    total_amount=product.price * j,
                    payment_method="Cash on Delivery",
                    payment_status="Pending",
                    created_at=datetime.utcnow() - timedelta(days=j * 3)
                )
                db.add(order)
                db.flush()
                db.add(
                    OrderItem(
                        order_id=order.id,
                        product_id=product.id,
                        product_name=product.name,
                        size=(product.sizes.split(",")[0] if product.sizes else "M"),
                        quantity=j,
                        unit_price=product.price,
                    )
                )
        db.flush()

    # Create user activity logs
    if db.query(UserActivity).count() == 0 and users:
        activity_types = ["login", "view_product", "add_to_cart", "place_order", "profile_update"]
        for user in users:
            for i in range(5, 15):
                activity = UserActivity(
                    user_id=user.id,
                    activity_type=activity_types[i % len(activity_types)],
                    activity_details=f'{{"action": "{activity_types[i % len(activity_types)]}"}}',
                    page_url="/",
                    ip_address="127.0.0.1",
                    created_at=datetime.utcnow() - timedelta(days=i, hours=i)
                )
                db.add(activity)
        db.flush()

    # Create audit logs
    if db.query(AuditLog).count() == 0:
        audit_actions = [
            ("user_created", "user", "1"),
            ("product_updated", "product", "SH-TS-001"),
            ("order_status_changed", "order", "1"),
            ("login_success", "user", "1"),
            ("password_changed", "user", "1"),
        ]
        for i, (action, entity_type, entity_id) in enumerate(audit_actions * 3):
            audit = AuditLog(
                user_id=1 if admin else None,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                new_values=f'{{"status": "completed", "timestamp": "{datetime.utcnow().isoformat()}"}}',
                ip_address="127.0.0.1",
                created_at=datetime.utcnow() - timedelta(days=i * 2)
            )
            db.add(audit)

    db.commit()
