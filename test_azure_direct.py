#!/usr/bin/env python3
"""
Simple Azure OpenAI connection test
"""

import os
from dotenv import load_dotenv
from openai import AzureOpenAI

# Load environment variables
load_dotenv()

# Get Azure configuration
endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
key = os.getenv('AZURE_OPENAI_KEY')
deployment = os.getenv('AZURE_OPENAI_DEPLOYMENT')
api_version = os.getenv('AZURE_OPENAI_API_VERSION')

print("Azure OpenAI Configuration:")
print(f"Endpoint: {endpoint}")
print(f"Key: {'***' + key[-4:] if key else 'Not set'}")
print(f"Deployment: {deployment}")
print(f"API Version: {api_version}")
print()

try:
    # Initialize client
    client = AzureOpenAI(
        api_key=key,
        azure_endpoint=endpoint,
        api_version=api_version,
    )

    print("✅ Client initialized successfully")

    # Try to list models/deployments
    print("\nTrying to list available models...")
    try:
        models = client.models.list()
        print("Available models:")
        for model in models.data:
            print(f"  - {model.id}")
    except Exception as e:
        print(f"❌ Could not list models: {e}")

    # Try a simple completion
    print(f"\nTrying completion with deployment '{deployment}'...")
    try:
        response = client.chat.completions.create(
            model=deployment,
            messages=[{"role": "user", "content": "Hello, test message"}],
            max_tokens=50
        )
        print("✅ Completion successful!")
        print(f"Response: {response.choices[0].message.content}")
    except Exception as e:
        print(f"❌ Completion failed: {e}")

except Exception as e:
    print(f"❌ Client initialization failed: {e}")