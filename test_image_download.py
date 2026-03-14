#!/usr/bin/env python3
"""
Simple test script to verify image download functionality.
Tests the download_image function with a sample image URL.
"""

import os
import requests
from pathlib import Path
from typing import Tuple, Optional

IMAGES_DIR = "images"

def download_image(url: str, filepath_base: str) -> Tuple[bool, Optional[str]]:
    """
    Download an image from a URL and save it to the specified filepath.
    The actual filepath will have the correct extension based on Content-Type.
    Returns tuple of (success: bool, final_filepath: str | None).
    """
    try:
        # Add User-Agent header to avoid potential blocking
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, timeout=10, stream=True, headers=headers, verify=True)
        response.raise_for_status()
        
        # Determine file extension from Content-Type or URL
        content_type = response.headers.get('Content-Type', '')
        if 'jpeg' in content_type or 'jpg' in content_type:
            ext = '.jpg'
        elif 'png' in content_type:
            ext = '.png'
        elif 'gif' in content_type:
            ext = '.gif'
        elif 'webp' in content_type:
            ext = '.webp'
        else:
            # Fallback: try to extract from URL
            url_lower = url.lower()
            if '.png' in url_lower:
                ext = '.png'
            elif '.gif' in url_lower:
                ext = '.gif'
            elif '.webp' in url_lower:
                ext = '.webp'
            else:
                ext = '.jpg'  # Default fallback
        
        # Add correct extension to filepath
        final_filepath = filepath_base + ext
        
        with open(final_filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return True, final_filepath
    except Exception as e:
        print(f"      ⚠️  Failed to download image: {e}")
        return False, None

def test_image_download():
    """Test downloading a sample image from the internet."""
    
    # Ensure images directory exists
    Path(IMAGES_DIR).mkdir(parents=True, exist_ok=True)
    
    # Test with a public sample image (using a reliable test image URL)
    test_url = "https://via.placeholder.com/500x500.jpg"
    test_filename_base = "test_image"
    test_filepath_base = os.path.join(IMAGES_DIR, test_filename_base)
    
    print(f"Testing image download functionality...")
    print(f"URL: {test_url}")
    print(f"Destination base: {test_filepath_base}")
    
    # Test the download
    success, final_filepath = download_image(test_url, test_filepath_base)
    
    if success and final_filepath and os.path.exists(final_filepath):
        file_size = os.path.getsize(final_filepath)
        print(f"✅ Image download successful!")
        print(f"   File size: {file_size} bytes")
        print(f"   Final location: {final_filepath}")
        
        # Clean up test file
        os.remove(final_filepath)
        print(f"   Test file cleaned up")
        return True
    else:
        print(f"❌ Image download failed!")
        return False

if __name__ == "__main__":
    import sys
    success = test_image_download()
    sys.exit(0 if success else 1)
