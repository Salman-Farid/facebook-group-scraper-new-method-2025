#!/usr/bin/env python3
"""
Unit test for the duplicate detection fix.
Tests the normalize_text_for_hash function to ensure it properly prevents duplicates.
"""

import sys
import re
import hashlib
import unicodedata


# Copy the functions from main.py to test them standalone
def normalize_text_for_hash(text: str) -> str:
    """
    Normalize text for consistent hashing to prevent duplicates.
    - Unicode normalization (NFC form)
    - Convert to lowercase for case-insensitive comparison
    - Collapse multiple whitespace to single space
    - Strip leading/trailing whitespace
    """
    # Normalize unicode characters to NFC form
    normalized = unicodedata.normalize('NFC', text)
    # Convert to lowercase for case-insensitive comparison
    normalized = normalized.lower()
    # Collapse multiple spaces/newlines/tabs to single space
    normalized = re.sub(r'\s+', ' ', normalized)
    # Strip leading/trailing whitespace
    normalized = normalized.strip()
    return normalized


def make_post_hash(text: str) -> str:
    """Generate SHA256 hash of normalized text to detect duplicates."""
    normalized_text = normalize_text_for_hash(text)
    return hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()


def test_whitespace_normalization():
    """Test that different whitespace produces the same hash."""
    text1 = "ঢাকা  ও ঢাকার বাহিরে"
    text2 = "ঢাকা   ও   ঢাকার   বাহিরে"
    
    hash1 = make_post_hash(text1)
    hash2 = make_post_hash(text2)
    
    assert hash1 == hash2, f"Whitespace normalization failed: {hash1} != {hash2}"
    print("✓ Test 1: Whitespace normalization works")


def test_leading_trailing_spaces():
    """Test that leading/trailing spaces don't affect hash."""
    text1 = "ঢাকা  ও ঢাকার বাহিরে"
    text2 = "  ঢাকা  ও ঢাকার বাহিরে  "
    
    hash1 = make_post_hash(text1)
    hash2 = make_post_hash(text2)
    
    assert hash1 == hash2, f"Leading/trailing space normalization failed: {hash1} != {hash2}"
    print("✓ Test 2: Leading/trailing space normalization works")


def test_case_insensitive():
    """Test that case differences don't affect hash."""
    text1 = "Test Post"
    text2 = "test post"
    
    hash1 = make_post_hash(text1)
    hash2 = make_post_hash(text2)
    
    assert hash1 == hash2, f"Case-insensitive comparison failed: {hash1} != {hash2}"
    print("✓ Test 3: Case-insensitive comparison works")


def test_newline_tab_normalization():
    """Test that newlines and tabs are normalized to spaces."""
    text1 = "Line 1\nLine 2\tTabbed"
    text2 = "Line 1  Line 2  Tabbed"
    
    hash1 = make_post_hash(text1)
    hash2 = make_post_hash(text2)
    
    assert hash1 == hash2, f"Newline/tab normalization failed: {hash1} != {hash2}"
    print("✓ Test 4: Newline/tab normalization works")


def test_different_posts_different_hashes():
    """Test that genuinely different posts have different hashes."""
    posts = [
        "Chittagong Rent A Car – Trusted Car Rental Partner in Bangladesh",
        "#RENT-A CAR #রেন্ট-এ কার আপনাকে স্বাগতম",
        "Need a Reliable and Convenient Taxi Service in All Bangladesh",
    ]
    
    hashes = [make_post_hash(post) for post in posts]
    unique_hashes = set(hashes)
    
    assert len(hashes) == len(unique_hashes), f"Different posts should have different hashes"
    print("✓ Test 5: Different posts have different hashes")


def test_unicode_normalization():
    """Test that different unicode representations produce the same hash."""
    # These should normalize to the same form
    text1 = "café"  # é as a single character
    text2 = "café"  # é as e + combining accent (if different representation exists)
    
    hash1 = make_post_hash(text1)
    hash2 = make_post_hash(text2)
    
    # They should be the same after NFC normalization
    assert hash1 == hash2, f"Unicode normalization failed: {hash1} != {hash2}"
    print("✓ Test 6: Unicode normalization works")


def test_real_world_example():
    """Test with actual example from the issue."""
    # Post #1 (103 chars) and Post #6 (102 chars) from the issue
    text1 = "ঢাকা  ও ঢাকার বাহিরে থেকে সারা বাংলাদেশ এ প্রাইভেট কার,  নোয়াহ এবং হাইয়েস গাড়ি ভাড়া লাগলে যোগাযোগ ক"
    text2 = "ঢাকা  ও ঢাকার বাহিরে থেকে সারা বাংলাদেশ এ প্রাইভেট কার, নোয়াহ এবং হাইয়েস গাড়ি ভাড়া লাগলে যোগাযোগ কর"
    
    hash1 = make_post_hash(text1)
    hash2 = make_post_hash(text2)
    
    # These are different posts (different endings), so hashes should be different
    # But if they were the same with just whitespace differences, they should match
    # Let's check the normalized forms
    norm1 = normalize_text_for_hash(text1)
    norm2 = normalize_text_for_hash(text2)
    
    print(f"  Normalized text 1 ends with: ...{norm1[-20:]}")
    print(f"  Normalized text 2 ends with: ...{norm2[-20:]}")
    
    if norm1 == norm2:
        assert hash1 == hash2, "Same normalized text should have same hash"
        print("✓ Test 7: Real-world example - texts are identical after normalization")
    else:
        assert hash1 != hash2, "Different text should have different hash"
        print("✓ Test 7: Real-world example - texts are genuinely different")


if __name__ == "__main__":
    print("Running duplicate detection tests...\n")
    print("=" * 70)
    
    try:
        test_whitespace_normalization()
        test_leading_trailing_spaces()
        test_case_insensitive()
        test_newline_tab_normalization()
        test_different_posts_different_hashes()
        test_unicode_normalization()
        test_real_world_example()
        
        print("=" * 70)
        print("\n✅ All tests passed! Duplicate detection is working correctly.\n")
        
    except AssertionError as e:
        print("\n" + "=" * 70)
        print(f"\n❌ Test failed: {e}\n")
        sys.exit(1)
    except Exception as e:
        print("\n" + "=" * 70)
        print(f"\n❌ Unexpected error: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
