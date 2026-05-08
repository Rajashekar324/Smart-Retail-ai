"""
Azure AI Language Text Analytics Service
========================================

Provides sentiment analysis for customer reviews using Azure AI Language REST API.

Features:
- Sentiment analysis (positive, negative, neutral, mixed)
- Confidence scores for each sentiment
- Production-ready with proper error handling
"""

import logging
import requests
from typing import Dict, Optional, Any
from dataclasses import dataclass
from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class SentimentResult:
    """Result of sentiment analysis"""
    sentiment: str  # positive, negative, neutral, mixed
    confidence_positive: float
    confidence_neutral: float
    confidence_negative: float
    confidence_scores: Dict[str, float]
    success: bool
    error_message: Optional[str] = None


class AzureTextAnalyticsService:
    """
    Azure AI Language Text Analytics Service for sentiment analysis.
    
    Uses Azure AI Language REST API v3.1 for analyzing customer review sentiment.
    """
    
    def __init__(self):
        # Safely get settings with defaults
        raw_endpoint = settings.azure_language_endpoint or ""
        self.endpoint = raw_endpoint.rstrip('/') if raw_endpoint else ""
        self.key = settings.azure_language_key or ""
        self.enabled = settings.azure_language_enabled and bool(self.endpoint) and bool(self.key)
        
        # API version and endpoint
        self.api_version = "3.1"
        self.sentiment_url = f"{self.endpoint}/text/analytics/v3.1/sentiment" if self.endpoint else ""
        
        if self.enabled:
            logger.info(f"Azure Text Analytics Service initialized with endpoint: {self.endpoint[:30]}...")
            logger.info(f"Full URL: {self.sentiment_url}")
        else:
            missing = []
            if not settings.azure_language_enabled:
                missing.append("AZURE_LANGUAGE_ENABLED (set to 'true' in .env)")
                logger.error("AZURE_LANGUAGE_ENABLED is False or not set - Set AZURE_LANGUAGE_ENABLED=true in .env file")
            if not self.endpoint:
                missing.append("AZURE_LANGUAGE_ENDPOINT")
                logger.error("AZURE_LANGUAGE_ENDPOINT is empty - Add your Azure AI Language endpoint URL")
            if not self.key:
                missing.append("AZURE_LANGUAGE_KEY")
                logger.error("AZURE_LANGUAGE_KEY is empty - Add your Azure AI Language key")
            logger.warning(f"Azure Text Analytics disabled - missing: {', '.join(missing)}")
    
    def analyze_sentiment(self, text: str) -> SentimentResult:
        """
        Analyze sentiment of a single text document.
        
        Args:
            text: The review text to analyze
            
        Returns:
            SentimentResult with sentiment label and confidence scores
        """
        if not self.enabled:
            logger.warning("Azure Text Analytics not enabled, returning neutral sentiment")
            return self._fallback_sentiment(text)
        
        if not text or len(text.strip()) == 0:
            return SentimentResult(
                sentiment="neutral",
                confidence_positive=0.33,
                confidence_neutral=0.34,
                confidence_negative=0.33,
                confidence_scores={"positive": 0.33, "neutral": 0.34, "negative": 0.33},
                success=True,
                error_message="Empty text provided"
            )
        
        try:
            # Prepare request payload
            documents = {
                "documents": [
                    {
                        "id": "1",
                        "language": "en",
                        "text": text[:5000]  # Azure limit is 5120 characters per document
                    }
                ]
            }
            
            # Set headers
            headers = {
                "Ocp-Apim-Subscription-Key": self.key,
                "Content-Type": "application/json"
            }
            
            # Make API request
            logger.info(f"Sending sentiment analysis request to Azure AI Language")
            response = requests.post(
                self.sentiment_url,
                headers=headers,
                json=documents,
                timeout=30
            )
            
            response.raise_for_status()
            result = response.json()
            
            # Parse response
            if "documents" in result and len(result["documents"]) > 0:
                doc = result["documents"][0]
                sentiment = doc.get("sentiment", "neutral")
                confidence = doc.get("confidenceScores", {})
                
                # Ensure confidence is a dictionary (Azure sometimes returns unexpected formats)
                if isinstance(confidence, str):
                    try:
                        import json
                        confidence = json.loads(confidence)
                    except:
                        confidence = {"positive": 0.33, "neutral": 0.34, "negative": 0.33}
                elif not isinstance(confidence, dict):
                    confidence = {"positive": 0.33, "neutral": 0.34, "negative": 0.33}
                
                sentiment_result = SentimentResult(
                    sentiment=sentiment,
                    confidence_positive=confidence.get("positive", 0.0),
                    confidence_neutral=confidence.get("neutral", 0.0),
                    confidence_negative=confidence.get("negative", 0.0),
                    confidence_scores=confidence,
                    success=True
                )
                
                logger.info(f"Sentiment analyzed: {sentiment} (positive: {sentiment_result.confidence_positive:.2f})")
                return sentiment_result
            
            else:
                error_msg = result.get("errors", [{}])[0].get("message", "Unknown API error")
                logger.error(f"Azure API error: {error_msg}")
                return SentimentResult(
                    sentiment="neutral",
                    confidence_positive=0.33,
                    confidence_neutral=0.34,
                    confidence_negative=0.33,
                    confidence_scores={"positive": 0.33, "neutral": 0.34, "negative": 0.33},
                    success=False,
                    error_message=error_msg
                )
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Azure API request failed: {e}")
            return self._fallback_sentiment(text, f"API request failed: {str(e)}")
        
        except Exception as e:
            logger.error(f"Unexpected error in sentiment analysis: {e}")
            return self._fallback_sentiment(text, f"Unexpected error: {str(e)}")
    
    def _fallback_sentiment(self, text: str, error_message: str = "Service disabled") -> SentimentResult:
        """
        Fallback sentiment analysis using simple keyword matching when Azure is unavailable.
        
        Args:
            text: The review text
            error_message: Error message to include
            
        Returns:
            SentimentResult with estimated sentiment
        """
        text_lower = text.lower() if text else ""
        
        # Simple positive/negative keyword matching
        positive_words = ['good', 'great', 'excellent', 'amazing', 'love', 'perfect', 'best', 'happy', 
                         'satisfied', 'awesome', 'fantastic', 'wonderful', 'beautiful', 'nice', 'quality',
                         'recommend', 'fast', 'quick', 'smooth', 'easy', 'comfortable', 'worth']
        
        negative_words = ['bad', 'terrible', 'awful', 'worst', 'hate', 'disappointed', 'poor', 'broken',
                         'defective', 'waste', 'slow', 'difficult', 'hard', 'uncomfortable', 'cheap',
                         'fake', 'damaged', 'wrong', 'missing', 'never', 'avoid', 'return']
        
        positive_count = sum(1 for word in positive_words if word in text_lower)
        negative_count = sum(1 for word in negative_words if word in text_lower)
        
        if positive_count > negative_count:
            sentiment = "positive"
            scores = {"positive": 0.75, "neutral": 0.20, "negative": 0.05}
        elif negative_count > positive_count:
            sentiment = "negative"
            scores = {"positive": 0.05, "neutral": 0.20, "negative": 0.75}
        else:
            sentiment = "neutral"
            scores = {"positive": 0.33, "neutral": 0.34, "negative": 0.33}
        
        logger.warning(f"Using fallback sentiment analysis: {sentiment}")
        
        return SentimentResult(
            sentiment=sentiment,
            confidence_positive=scores["positive"],
            confidence_neutral=scores["neutral"],
            confidence_negative=scores["negative"],
            confidence_scores=scores,
            success=True,  # Mark as success but with fallback
            error_message=f"Fallback mode: {error_message}"
        )
    
    def analyze_batch_sentiment(self, texts: list) -> list:
        """
        Analyze sentiment for multiple texts (batch processing).
        
        Args:
            texts: List of text strings to analyze
            
        Returns:
            List of SentimentResult objects
        """
        results = []
        for text in texts:
            result = self.analyze_sentiment(text)
            results.append(result)
        return results
    
    def get_service_status(self) -> Dict[str, Any]:
        """
        Get current service status and configuration.
        
        Returns:
            Dictionary with service status information
        """
        return {
            "enabled": self.enabled,
            "endpoint_configured": bool(self.endpoint),
            "key_configured": bool(self.key),
            "endpoint": self.endpoint[:30] + "..." if self.endpoint and len(self.endpoint) > 30 else self.endpoint,
            "api_version": self.api_version
        }


# Global service instance
azure_text_analytics = AzureTextAnalyticsService()


def analyze_review_sentiment(text: str) -> SentimentResult:
    """
    Convenience function to analyze sentiment of a review.
    
    Args:
        text: The review text
        
    Returns:
        SentimentResult with sentiment analysis
    """
    return azure_text_analytics.analyze_sentiment(text)
