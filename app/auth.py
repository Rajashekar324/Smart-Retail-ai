from datetime import datetime, timedelta
from fastapi import Request
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
import secrets
import string

from app.config import settings
from app.models import PasswordResetToken, RefreshToken, Session, User, UserActivity
from app.utils import read_session_token

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_refresh_token(user_id: int, db: Session) -> str:
    token = secrets.token_urlsafe(64)
    expires_at = datetime.utcnow() + timedelta(days=settings.refresh_token_expire_days)
    
    refresh_token = RefreshToken(
        token=token,
        user_id=user_id,
        expires_at=expires_at
    )
    db.add(refresh_token)
    db.commit()
    
    return token


def verify_refresh_token(token: str, db: Session) -> int | None:
    refresh_token = db.query(RefreshToken).filter(
        RefreshToken.token == token,
        RefreshToken.is_revoked == False,
        RefreshToken.expires_at > datetime.utcnow()
    ).first()
    
    if refresh_token:
        return refresh_token.user_id
    return None


def revoke_refresh_token(token: str, db: Session) -> bool:
    refresh_token = db.query(RefreshToken).filter(RefreshToken.token == token).first()
    if refresh_token:
        refresh_token.is_revoked = True
        db.commit()
        return True
    return False


def create_password_reset_token(user_id: int, db: Session) -> str:
    token = secrets.token_urlsafe(64)
    expires_at = datetime.utcnow() + timedelta(hours=settings.password_reset_expire_hours)
    
    reset_token = PasswordResetToken(
        token=token,
        user_id=user_id,
        expires_at=expires_at
    )
    db.add(reset_token)
    db.commit()
    
    return token


def verify_password_reset_token(token: str, db: Session) -> int | None:
    reset_token = db.query(PasswordResetToken).filter(
        PasswordResetToken.token == token,
        PasswordResetToken.is_used == False,
        PasswordResetToken.expires_at > datetime.utcnow()
    ).first()
    
    if reset_token:
        return reset_token.user_id
    return None


def mark_password_reset_token_used(token: str, db: Session) -> bool:
    reset_token = db.query(PasswordResetToken).filter(PasswordResetToken.token == token).first()
    if reset_token:
        reset_token.is_used = True
        db.commit()
        return True
    return False


def create_user_session(user_id: int, request: Request, db: Session) -> str:
    session_id = secrets.token_urlsafe(32)
    
    user_agent = request.headers.get("user-agent", "")
    ip_address = request.client.host if request.client else "unknown"
    
    device_type = "Desktop"
    if "Mobile" in user_agent:
        device_type = "Mobile"
    elif "Tablet" in user_agent:
        device_type = "Tablet"
    
    browser = "Unknown"
    if "Chrome" in user_agent:
        browser = "Chrome"
    elif "Firefox" in user_agent:
        browser = "Firefox"
    elif "Safari" in user_agent:
        browser = "Safari"
    elif "Edge" in user_agent:
        browser = "Edge"
    
    session = Session(
        session_id=session_id,
        user_id=user_id,
        ip_address=ip_address,
        user_agent=user_agent,
        device_type=device_type,
        browser=browser
    )
    db.add(session)
    db.commit()
    
    return session_id


def get_user_sessions(user_id: int, db: Session) -> list[Session]:
    return db.query(Session).filter(
        Session.user_id == user_id,
        Session.is_active == True
    ).order_by(Session.created_at.desc()).all()


def revoke_session(session_id: str, db: Session) -> bool:
    session = db.query(Session).filter(Session.session_id == session_id).first()
    if session:
        session.is_active = False
        db.commit()
        return True
    return False


def revoke_all_sessions(user_id: int, db: Session, except_session_id: str | None = None) -> int:
    query = db.query(Session).filter(
        Session.user_id == user_id,
        Session.is_active == True
    )
    
    if except_session_id:
        query = query.filter(Session.session_id != except_session_id)
    
    sessions = query.all()
    for session in sessions:
        session.is_active = False
    
    db.commit()
    return len(sessions)


def log_user_activity(user_id: int, activity_type: str, db: Session, 
                      activity_details: str | None = None, page_url: str | None = None,
                      request: Request | None = None):
    ip_address = None
    if request and request.client:
        ip_address = request.client.host
    
    activity = UserActivity(
        user_id=user_id,
        activity_type=activity_type,
        activity_details=activity_details,
        page_url=page_url,
        ip_address=ip_address
    )
    db.add(activity)
    db.commit()


def get_user_analytics(user_id: int, db: Session) -> dict:
    from sqlalchemy import func
    
    total_activities = db.query(func.count(UserActivity.id)).filter(
        UserActivity.user_id == user_id
    ).scalar()
    
    logins = db.query(func.count(UserActivity.id)).filter(
        UserActivity.user_id == user_id,
        UserActivity.activity_type == "login"
    ).scalar()
    
    active_sessions = db.query(func.count(Session.id)).filter(
        Session.user_id == user_id,
        Session.is_active == True
    ).scalar()
    
    recent_activities = db.query(UserActivity).filter(
        UserActivity.user_id == user_id
    ).order_by(UserActivity.created_at.desc()).limit(20).all()
    
    return {
        "total_activities": total_activities or 0,
        "total_logins": logins or 0,
        "active_sessions": active_sessions or 0,
        "recent_activities": recent_activities
    }


def get_current_user(request: Request, db: Session):
    token = request.cookies.get("session_token")
    if not token:
        return None

    payload = read_session_token(token)
    if not payload:
        return None

    user_id = payload.get("user_id")
    if not user_id:
        return None

    return db.query(User).filter(User.id == user_id).first()