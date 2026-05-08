"""
Review Service with MongoDB and Azure Sentiment Analysis
=========================================================

Manages customer reviews with:
- MongoDB storage
- Azure AI Language sentiment analysis
- Review validation and duplicate prevention
- Analytics for admin dashboard
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from bson import ObjectId
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.config import settings
from app.services.azure_text_analytics import azure_text_analytics, SentimentResult

logger = logging.getLogger(__name__)


@dataclass
class ReviewCreate:
    """Data class for creating a new review"""
    user_id: int
    order_id: int
    product_id: int
    review_text: str
    rating: int


@dataclass
class ReviewResponse:
    """Data class for review response"""
    id: str
    user_id: int
    order_id: int
    product_id: int
    review_text: str
    rating: int
    sentiment: str
    confidence_scores: Dict[str, float]
    created_at: datetime
    user_name: Optional[str] = None
    product_name: Optional[str] = None


class ReviewService:
    """
    Service for managing customer reviews with sentiment analysis.
    Uses MongoDB for storage and Azure AI Language for sentiment analysis.
    """
    
    def __init__(self):
        self.client: Optional[MongoClient] = None
        self.db = None
        self.reviews_collection = None
        self._connect()
    
    def _connect(self):
        """Establish MongoDB connection"""
        try:
            self.client = MongoClient(settings.mongodb_reviews_uri, serverSelectionTimeoutMS=5000)
            self.db = self.client[settings.mongodb_reviews_db]
            self.reviews_collection = self.db["reviews"]
            
            # Create unique index to prevent duplicate reviews
            self.reviews_collection.create_index(
                [("user_id", ASCENDING), ("order_id", ASCENDING), ("product_id", ASCENDING)],
                unique=True,
                name="unique_review_index"
            )
            
            # Create indexes for efficient queries
            self.reviews_collection.create_index([("product_id", ASCENDING)])
            self.reviews_collection.create_index([("sentiment", ASCENDING)])
            self.reviews_collection.create_index([("created_at", DESCENDING)])
            self.reviews_collection.create_index([("user_id", ASCENDING)])
            
            logger.info("ReviewService connected to MongoDB successfully")
            
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            self.client = None
            self.db = None
            self.reviews_collection = None
    
    def _ensure_connection(self) -> bool:
        """Ensure MongoDB connection is active"""
        if self.reviews_collection is None:
            logger.error("MongoDB not connected")
            return False
        return True
    
    def create_review(
        self,
        user_id: int,
        order_id: int,
        product_id: int,
        review_text: str,
        rating: int,
        user_name: Optional[str] = None,
        product_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new review with sentiment analysis.
        
        Args:
            user_id: ID of the user submitting the review
            order_id: ID of the order being reviewed
            product_id: ID of the product being reviewed
            review_text: The review text content
            rating: Star rating (1-5)
            user_name: Optional user name for display
            product_name: Optional product name for display
            
        Returns:
            Dictionary with success status and review data or error message
        """
        if not self._ensure_connection():
            return {"success": False, "error": "Database connection failed"}
        
        # Validate rating
        if not 1 <= rating <= 5:
            return {"success": False, "error": "Rating must be between 1 and 5"}
        
        # Validate review text length
        if not review_text or len(review_text.strip()) < 5:
            return {"success": False, "error": "Review text must be at least 5 characters"}
        
        if len(review_text) > 1000:
            return {"success": False, "error": "Review text must not exceed 1000 characters"}
        
        # Sanitize review text
        review_text = review_text.strip()
        
        # Perform Azure sentiment analysis
        logger.info(f"Analyzing sentiment for review from user {user_id}")
        sentiment_result = azure_text_analytics.analyze_sentiment(review_text)
        
        # Ensure confidence_scores is a dictionary
        confidence_scores = sentiment_result.confidence_scores
        if isinstance(confidence_scores, str):
            try:
                import json
                confidence_scores = json.loads(confidence_scores)
            except:
                confidence_scores = {"positive": 0.33, "neutral": 0.34, "negative": 0.33}
        elif not isinstance(confidence_scores, dict):
            confidence_scores = {"positive": 0.33, "neutral": 0.34, "negative": 0.33}
        
        # Prepare review document
        review_doc = {
            "user_id": user_id,
            "order_id": order_id,
            "product_id": product_id,
            "review_text": review_text,
            "rating": rating,
            "sentiment": sentiment_result.sentiment,
            "confidence_scores": confidence_scores,
            "sentiment_confidence_positive": sentiment_result.confidence_positive,
            "sentiment_confidence_neutral": sentiment_result.confidence_neutral,
            "sentiment_confidence_negative": sentiment_result.confidence_negative,
            "sentiment_analysis_success": sentiment_result.success,
            "sentiment_error": sentiment_result.error_message,
            "user_name": user_name,
            "product_name": product_name,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        try:
            # Insert into MongoDB
            result = self.reviews_collection.insert_one(review_doc)
            review_id = str(result.inserted_id)
            
            logger.info(f"Review created successfully: {review_id}")
            
            return {
                "success": True,
                "review": {
                    "id": review_id,
                    "user_id": user_id,
                    "order_id": order_id,
                    "product_id": product_id,
                    "review_text": review_text,
                    "rating": rating,
                    "sentiment": sentiment_result.sentiment,
                    "confidence_scores": confidence_scores,
                    "created_at": review_doc["created_at"].isoformat()
                }
            }
            
        except DuplicateKeyError:
            logger.warning(f"Duplicate review attempt: user={user_id}, order={order_id}, product={product_id}")
            return {"success": False, "error": "You have already reviewed this product for this order"}
        
        except PyMongoError as e:
            logger.error(f"Database error creating review: {e}")
            return {"success": False, "error": f"Database error: {str(e)}"}
        
        except Exception as e:
            logger.error(f"Unexpected error creating review: {e}")
            return {"success": False, "error": f"Unexpected error: {str(e)}"}
    
    def has_user_reviewed(self, user_id: int, order_id: int, product_id: int) -> bool:
        """
        Check if user has already reviewed a specific product in an order.
        
        Args:
            user_id: User ID
            order_id: Order ID
            product_id: Product ID
            
        Returns:
            True if review exists, False otherwise
        """
        if not self._ensure_connection():
            return False
        
        try:
            count = self.reviews_collection.count_documents({
                "user_id": user_id,
                "order_id": order_id,
                "product_id": product_id
            })
            return count > 0
        except Exception as e:
            logger.error(f"Error checking review existence: {e}")
            return False
    
    def get_reviews_by_product(self, product_id: int, limit: int = 50) -> List[Dict]:
        """
        Get all reviews for a specific product.
        
        Args:
            product_id: Product ID
            limit: Maximum number of reviews to return
            
        Returns:
            List of review documents
        """
        if not self._ensure_connection():
            return []
        
        try:
            cursor = self.reviews_collection.find(
                {"product_id": product_id}
            ).sort("created_at", DESCENDING).limit(limit)
            
            reviews = []
            for doc in cursor:
                doc["id"] = str(doc.pop("_id"))
                doc["created_at"] = doc["created_at"].isoformat() if isinstance(doc.get("created_at"), datetime) else doc.get("created_at")
                doc["updated_at"] = doc["updated_at"].isoformat() if isinstance(doc.get("updated_at"), datetime) else doc.get("updated_at")
                reviews.append(doc)
            
            return reviews
            
        except Exception as e:
            logger.error(f"Error fetching reviews by product: {e}")
            return []
    
    def get_reviews_by_order(self, order_id: int) -> List[Dict]:
        """
        Get all reviews for a specific order.
        
        Args:
            order_id: Order ID
            
        Returns:
            List of review documents
        """
        if not self._ensure_connection():
            return []
        
        try:
            cursor = self.reviews_collection.find({"order_id": order_id}).sort("created_at", DESCENDING)
            
            reviews = []
            for doc in cursor:
                doc["id"] = str(doc.pop("_id"))
                doc["created_at"] = doc["created_at"].isoformat() if isinstance(doc.get("created_at"), datetime) else doc.get("created_at")
                doc["updated_at"] = doc["updated_at"].isoformat() if isinstance(doc.get("updated_at"), datetime) else doc.get("updated_at")
                reviews.append(doc)
            
            return reviews
            
        except Exception as e:
            logger.error(f"Error fetching reviews by order: {e}")
            return []
    
    def get_recent_reviews(self, limit: int = 20) -> List[Dict]:
        """
        Get most recent reviews for admin dashboard.
        
        Args:
            limit: Maximum number of reviews to return
            
        Returns:
            List of review documents
        """
        if not self._ensure_connection():
            return []
        
        try:
            cursor = self.reviews_collection.find().sort("created_at", DESCENDING).limit(limit)
            
            reviews = []
            for doc in cursor:
                doc["id"] = str(doc.pop("_id"))
                doc["created_at"] = doc["created_at"].isoformat() if isinstance(doc.get("created_at"), datetime) else doc.get("created_at")
                doc["updated_at"] = doc["updated_at"].isoformat() if isinstance(doc.get("updated_at"), datetime) else doc.get("updated_at")
                reviews.append(doc)
            
            return reviews
            
        except Exception as e:
            logger.error(f"Error fetching recent reviews: {e}")
            return []
    
    def get_sentiment_analytics(self) -> Dict[str, Any]:
        """
        Get sentiment analytics for admin dashboard.
        
        Returns:
            Dictionary with sentiment statistics and trends
        """
        if not self._ensure_connection():
            return {"error": "Database not connected"}
        
        try:
            # Total reviews count
            total_reviews = self.reviews_collection.count_documents({})
            
            if total_reviews == 0:
                return {
                    "total_reviews": 0,
                    "sentiment_distribution": {},
                    "average_rating": 0,
                    "percentages": {"positive": 0, "neutral": 0, "negative": 0}
                }
            
            # Sentiment distribution
            sentiment_pipeline = [
                {"$group": {
                    "_id": "$sentiment",
                    "count": {"$sum": 1}
                }}
            ]
            sentiment_result = list(self.reviews_collection.aggregate(sentiment_pipeline))
            
            sentiment_distribution = {item["_id"]: item["count"] for item in sentiment_result}
            
            # Calculate percentages
            positive_count = sentiment_distribution.get("positive", 0)
            neutral_count = sentiment_distribution.get("neutral", 0)
            negative_count = sentiment_distribution.get("negative", 0)
            mixed_count = sentiment_distribution.get("mixed", 0)
            
            # Treat mixed as neutral for simplicity
            neutral_count += mixed_count
            
            percentages = {
                "positive": round((positive_count / total_reviews) * 100, 1),
                "neutral": round((neutral_count / total_reviews) * 100, 1),
                "negative": round((negative_count / total_reviews) * 100, 1)
            }
            
            # Average rating
            rating_pipeline = [
                {"$group": {
                    "_id": None,
                    "average_rating": {"$avg": "$rating"}
                }}
            ]
            rating_result = list(self.reviews_collection.aggregate(rating_pipeline))
            average_rating = round(rating_result[0]["average_rating"], 2) if rating_result else 0
            
            # Daily sentiment trends (last 30 days, inclusive of today)
            from datetime import timedelta
            thirty_days_ago = datetime.utcnow() - timedelta(days=29)
            
            try:
                trends_pipeline = [
                    {
                        "$match": {
                            "created_at": {"$gte": thirty_days_ago}
                        }
                    },
                    {
                        "$group": {
                            "_id": {
                                "date": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
                                "sentiment": "$sentiment"
                            },
                            "count": {"$sum": 1}
                        }
                    },
                    {"$sort": {"_id.date": 1}}
                ]
                
                trends_raw = list(self.reviews_collection.aggregate(trends_pipeline))
            except Exception as e:
                logger.warning(f"MongoDB aggregation failed, using fallback: {e}")
                # Fallback: fetch reviews and process in Python
                recent_reviews = list(self.reviews_collection.find(
                    {"created_at": {"$gte": thirty_days_ago}},
                    {"created_at": 1, "sentiment": 1}
                ))
                
                trends_raw = []
                from collections import defaultdict
                date_sentiment_counts = defaultdict(lambda: defaultdict(int))
                
                for review in recent_reviews:
                    if isinstance(review.get("created_at"), datetime):
                        date_str = review["created_at"].strftime("%Y-%m-%d")
                        sentiment = review.get("sentiment", "neutral")
                        date_sentiment_counts[date_str][sentiment] += 1
                
                for date, sentiments in date_sentiment_counts.items():
                    for sentiment, count in sentiments.items():
                        trends_raw.append({
                            "_id": {"date": date, "sentiment": sentiment},
                            "count": count
                        })
                
                trends_raw.sort(key=lambda x: x["_id"]["date"])
            
            # Format trends data for charts
            trends_by_date = {}
            for item in trends_raw:
                date = item["_id"]["date"]
                sentiment = item["_id"]["sentiment"]
                count = item["count"]
                
                if date not in trends_by_date:
                    trends_by_date[date] = {"positive": 0, "neutral": 0, "negative": 0}
                
                if sentiment in trends_by_date[date]:
                    trends_by_date[date][sentiment] += count
                elif sentiment == "mixed":
                    trends_by_date[date]["neutral"] += count
            
            # Build a complete 30-day trend series, filling missing dates with zeros.
            full_trends = []
            for day_index in range(30):
                day = thirty_days_ago + timedelta(days=day_index)
                day_str = day.strftime("%Y-%m-%d")
                day_data = trends_by_date.get(day_str, {"positive": 0, "neutral": 0, "negative": 0})
                full_trends.append({
                    "date": day_str,
                    "positive": day_data["positive"],
                    "neutral": day_data["neutral"],
                    "negative": day_data["negative"]
                })
            
            return {
                "total_reviews": total_reviews,
                "sentiment_distribution": sentiment_distribution,
                "average_rating": average_rating,
                "percentages": percentages,
                "trends": full_trends
            }
            
        except Exception as e:
            logger.error(f"Error generating sentiment analytics: {e}")
            return {"error": f"Analytics error: {str(e)}"}
    
    def delete_review(self, review_id: str, user_id: int) -> bool:
        """
        Delete a review (only by the owner or admin).
        
        Args:
            review_id: MongoDB review ID
            user_id: User ID requesting deletion (0 for admin override)
            
        Returns:
            True if deleted, False otherwise
        """
        if not self._ensure_connection():
            return False
        
        try:
            # Admin override (user_id=0) can delete any review
            if user_id == 0:
                query = {"_id": ObjectId(review_id)}
            else:
                query = {"_id": ObjectId(review_id), "user_id": user_id}
            
            result = self.reviews_collection.delete_one(query)
            return result.deleted_count > 0
            
        except Exception as e:
            logger.error(f"Error deleting review: {e}")
            return False
    
    def get_service_health(self) -> Dict[str, Any]:
        """
        Check service health status.
        
        Returns:
            Dictionary with health status
        """
        health = {
            "mongodb_connected": self._ensure_connection(),
            "azure_text_analytics": azure_text_analytics.get_service_status()
        }
        
        return health


# Global service instance
review_service = ReviewService()
