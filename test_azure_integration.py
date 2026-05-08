#!/usr/bin/env python3
"""
Test script for Azure OpenAI integration in StyleHub AI Store
Run this script to verify that your Azure OpenAI configuration is working correctly.
"""

import os
import sys
from pathlib import Path

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Add the app directory to the Python path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.llm_service import LLMService
from app.config import settings

def test_azure_openai_integration():
    """Test Azure OpenAI integration"""

    print("🔍 Testing Azure OpenAI Integration")
    print("=" * 50)

    # Check environment variables
    print("\n📋 Checking Environment Configuration:")
    azure_endpoint = os.getenv('AZURE_OPENAI_ENDPOINT', '')
    azure_key = os.getenv('AZURE_OPENAI_KEY', '')
    azure_deployment = os.getenv('AZURE_OPENAI_DEPLOYMENT', '')
    azure_api_version = os.getenv('AZURE_OPENAI_API_VERSION', '')

    print(f"Azure Endpoint: {'✅ Set' if azure_endpoint else '❌ Not set'}")
    print(f"Azure Key: {'✅ Set' if azure_key else '❌ Not set'}")
    print(f"Azure Deployment: {'✅ Set' if azure_deployment else '❌ Not set'}")
    print(f"Azure API Version: {'✅ Set' if azure_api_version else '❌ Not set'}")

    if not all([azure_endpoint, azure_key, azure_deployment, azure_api_version]):
        print("\n❌ Missing Azure OpenAI configuration. Please update your .env file:")
        print("""
AZURE_OPENAI_ENDPOINT=https://your-resource-name.openai.azure.com/
AZURE_OPENAI_KEY=your-azure-openai-key
AZURE_OPENAI_DEPLOYMENT=your-deployment-name
AZURE_OPENAI_API_VERSION=2024-02-01
        """)
        return False

    # Initialize LLM service
    print("\n🚀 Initializing LLM Service...")
    try:
        llm_service = LLMService()
        print("✅ LLM Service initialized successfully")
    except Exception as e:
        print(f"❌ Failed to initialize LLM Service: {e}")
        return False

    # Test basic generation
    print("\n🧪 Testing Basic Generation...")
    try:
        result = llm_service.generate_response("Hello, can you tell me about Azure OpenAI?")
        if result["success"]:
            print("✅ Basic generation successful")
            print(f"Response preview: {result['response'][:100]}...")
        else:
            print(f"❌ Basic generation failed: {result['error']}")
            return False
    except Exception as e:
        print(f"❌ Basic generation error: {e}")
        return False

    # Test RAG functionality
    print("\n🧪 Testing RAG Functionality...")
    try:
        result = llm_service.generate_with_rag("What are the benefits of using Azure OpenAI?")
        if result["success"]:
            print("✅ RAG generation successful")
            print(f"RAG used: {result.get('rag_used', False)}")
        else:
            print(f"❌ RAG generation failed: {result['error']}")
            return False
    except Exception as e:
        print(f"❌ RAG generation error: {e}")
        return False

    # Test data analysis
    print("\n🧪 Testing Data Analysis...")
    try:
        test_data = {
            "sales": [100, 120, 150, 130, 160],
            "customers": [50, 55, 60, 58, 65],
            "period": "last 5 months"
        }
        result = llm_service.analyze_data_with_llm(test_data, "sales analytics")
        if result["success"]:
            print("✅ Data analysis successful")
        else:
            print(f"❌ Data analysis failed: {result['error']}")
            return False
    except Exception as e:
        print(f"❌ Data analysis error: {e}")
        return False

    print("\n🎉 All tests passed! Azure OpenAI integration is working correctly.")
    return True

if __name__ == "__main__":
    success = test_azure_openai_integration()
    sys.exit(0 if success else 1)