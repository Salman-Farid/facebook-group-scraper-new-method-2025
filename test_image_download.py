#!/usr/bin/env python3
"""
Simple test script to verify image download functionality.
Tests the download_image function with a sample image URL.
"""

import os
import requests
from pathlib import Path

IMAGES_DIR = "images"

def download_image(url: str, filepath: str) -> bool:
    """
    Download an image from a URL and save it to the specified filepath.
    Returns True if successful, False otherwise.
    """
    try:
        response = requests.get(url, timeout=10, stream=True)
        response.raise_for_status()
        
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return True
    except Exception as e:
        print(f"      ⚠️  Failed to download image: {e}")
        return False

def test_image_download():
    """Test downloading a sample image from the internet."""
    
    # Ensure images directory exists
    Path(IMAGES_DIR).mkdir(parents=True, exist_ok=True)
    
    # Test with a public sample image (using a reliable test image URL)
    test_url = "https://via.placeholder.com/500x500.jpg"
    test_filename = "test_image.jpg"
    test_filepath = os.path.join(IMAGES_DIR, test_filename)
    
    print(f"Testing image download functionality...")
    print(f"URL: {test_url}")
    print(f"Destination: {test_filepath}")
    
    # Remove test file if it exists
    if os.path.exists(test_filepath):
        os.remove(test_filepath)
        print(f"Removed existing test file")
    
    # Test the download
    success = download_image(test_url, test_filepath)
    
    if success and os.path.exists(test_filepath):
        file_size = os.path.getsize(test_filepath)
        print(f"✅ Image download successful!")
        print(f"   File size: {file_size} bytes")
        print(f"   Location: {test_filepath}")
        
        # Clean up test file
        os.remove(test_filepath)
        print(f"   Test file cleaned up")
        return True
    else:
        print(f"❌ Image download failed!")
        return False

if __name__ == "__main__":
    import sys
    success = test_image_download()
    sys.exit(0 if success else 1)
