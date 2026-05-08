from datetime import datetime
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from app.config import settings


class MongoService:
    def __init__(self):
        self.client = None
        self.db = None
        try:
            self.client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=1500)
            self.client.server_info()
            self.db = self.client[settings.mongodb_db]
        except Exception:
            self.client = None
            self.db = None

    @property
    def available(self) -> bool:
        return self.db is not None

    def log_chat(self, payload: dict):
        if not self.available:
            return False
        try:
            payload["created_at"] = datetime.utcnow()
            self.db.chat_logs.insert_one(payload)
            return True
        except PyMongoError:
            return False

    def create_ticket(self, payload: dict):
        if not self.available:
            return None
        try:
            payload["created_at"] = datetime.utcnow()
            payload.setdefault("status", "Open")
            result = self.db.support_tickets.insert_one(payload)
            return str(result.inserted_id)
        except PyMongoError:
            return None

    def update_ticket_status(self, ticket_number: str, status: str, admin_note: str = ""):
        if not self.available:
            return False
        try:
            self.db.support_tickets.update_one(
                {"ticket_number": ticket_number},
                {"$set": {"status": status, "admin_note": admin_note, "updated_at": datetime.utcnow()}},
                upsert=False,
            )
            return True
        except PyMongoError:
            return False

    def get_dashboard_metrics(self) -> dict:
        sentiment_breakdown = {"positive": 0, "neutral": 0, "negative": 0}
        if not self.available:
            return {"sentiment_breakdown": sentiment_breakdown, "tickets": 0, "chats": 0}

        for row in self.db.chat_logs.aggregate([
            {"$group": {"_id": "$sentiment", "count": {"$sum": 1}}}
        ]):
            key = row.get("_id") or "neutral"
            sentiment_breakdown[key] = row.get("count", 0)

        return {
            "sentiment_breakdown": sentiment_breakdown,
            "tickets": self.db.support_tickets.count_documents({}),
            "chats": self.db.chat_logs.count_documents({}),
        }


mongo_service = MongoService()
