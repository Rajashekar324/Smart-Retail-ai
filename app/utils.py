import random
import string
from itsdangerous import URLSafeSerializer
from app.config import settings


serializer = URLSafeSerializer(settings.secret_key, salt="stylehub-session")


def generate_order_number() -> str:
    return "ORD" + "".join(random.choices(string.digits, k=8))


def generate_tracking_id() -> str:
    return "TRK" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))


def generate_ticket_number() -> str:
    return "TKT" + "".join(random.choices(string.digits, k=7))


def create_payment_reference() -> str:
    return "PAY" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))


def create_session_token(data: dict) -> str:
    return serializer.dumps(data)


def read_session_token(token: str):
    try:
        return serializer.loads(token)
    except Exception:
        return None
