#!/usr/bin/env python3
"""
Test for strict duplicate checking in the database.
Ensures that no duplicate posts can be saved regardless of how many times the script runs.
"""

import os
import psycopg2
import psycopg2.extras
from datetime import datetime, timezone
from dotenv import load_dotenv
import hashlib
import unicodedata
import re

# Load environment variables
load_dotenv()

# Import the functions from main.py
import sys
sys.path.insert(0, '/home/runner/work/facebook-group-scraper-new-method-2025/facebook-group-scraper-new-method-2025')
from main import normalize_text_for_hash, make_post_hash, post_exists_in_db, save_post_to_db

DB_CONFIG = {
    "user": os.getenv("SUPABASE_DB_USER"),
    "password": os.getenv("SUPABASE_DB_PASSWORD"),
    "host": os.getenv("SUPABASE_DB_HOST"),
    "port": int(os.getenv("SUPABASE_DB_PORT", "5432")),
    "dbname": os.getenv("SUPABASE_DB_NAME", "postgres"),
}


def test_post_exists_check():
    """Test that post_exists_in_db correctly identifies existing posts."""
    print("\n" + "="*70)
    print("Test 1: Checking if post_exists_in_db function works")
    print("="*70)
    
    # Skip if DB credentials are not available
    if not all([DB_CONFIG["user"], DB_CONFIG["password"], DB_CONFIG["host"]]):
        print("⚠️  Skipping database tests - credentials not available")
        return
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        
        # Create a test post with unique text
        test_text = f"TEST POST for strict duplicate checking - {datetime.now().isoformat()}"
        post_hash = make_post_hash(test_text)
        
        # Check that it doesn't exist initially
        exists_before = post_exists_in_db(conn, post_hash)
        print(f"Post exists before saving: {exists_before}")
        assert not exists_before, "Test post should not exist initially"
        
        # Create and save the test post
        test_post = {
            "post_text": test_text,
            "phone_numbers": [],
            "hashtags": [],
            "image_urls": {},
            "post_url": "https://facebook.com/test",
            "post_hash": post_hash,
            "scraped_at": datetime.now(timezone.utc),
        }
        
        saved = save_post_to_db(conn, test_post)
        print(f"Post saved successfully: {saved}")
        assert saved, "Post should be saved successfully"
        
        # Check that it exists after saving
        exists_after = post_exists_in_db(conn, post_hash)
        print(f"Post exists after saving: {exists_after}")
        assert exists_after, "Test post should exist after saving"
        
        # Try to save the same post again
        saved_again = save_post_to_db(conn, test_post)
        print(f"Post saved again (should be False): {saved_again}")
        assert not saved_again, "Duplicate post should not be saved"
        
        # Verify it still exists (and only once)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM facebook_group_posts WHERE post_hash = %s", (post_hash,))
            count = cur.fetchone()[0]
            print(f"Number of posts with this hash in DB: {count}")
            assert count == 1, f"Should have exactly 1 post with this hash, found {count}"
        
        # Clean up test data
        with conn.cursor() as cur:
            cur.execute("DELETE FROM facebook_group_posts WHERE post_hash = %s", (post_hash,))
        conn.commit()
        print("✓ Test data cleaned up")
        
        conn.close()
        print("\n✅ Test 1 PASSED: post_exists_in_db works correctly")
        
    except Exception as e:
        print(f"\n❌ Test 1 FAILED: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_strict_duplicate_prevention():
    """Test that duplicates with text variations are prevented."""
    print("\n" + "="*70)
    print("Test 2: Testing strict duplicate prevention with text variations")
    print("="*70)
    
    # Skip if DB credentials are not available
    if not all([DB_CONFIG["user"], DB_CONFIG["password"], DB_CONFIG["host"]]):
        print("⚠️  Skipping database tests - credentials not available")
        return
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        
        # Create test posts with variations
        base_time = datetime.now().isoformat()
        variations = [
            f"Test  Post  with  multiple  spaces {base_time}",
            f"  Test  Post  with  multiple  spaces {base_time}  ",
            f"TEST POST WITH MULTIPLE SPACES {base_time}",
            f"Test\tPost\twith\tmultiple\tspaces {base_time}",
            f"Test\nPost\nwith\nmultiple\nspaces {base_time}",
        ]
        
        # All variations should produce the same hash
        hashes = [make_post_hash(text) for text in variations]
        unique_hashes = set(hashes)
        print(f"Number of unique hashes from {len(variations)} variations: {len(unique_hashes)}")
        assert len(unique_hashes) == 1, f"All variations should produce the same hash, got {len(unique_hashes)} unique hashes"
        
        post_hash = hashes[0]
        
        # Ensure the post doesn't exist
        if post_exists_in_db(conn, post_hash):
            with conn.cursor() as cur:
                cur.execute("DELETE FROM facebook_group_posts WHERE post_hash = %s", (post_hash,))
            conn.commit()
            print("Cleaned up existing test data")
        
        # Try to save each variation
        saved_count = 0
        for i, text in enumerate(variations, 1):
            # Check if exists before saving
            exists_before = post_exists_in_db(conn, post_hash)
            
            test_post = {
                "post_text": text,
                "phone_numbers": [],
                "hashtags": [],
                "image_urls": {},
                "post_url": f"https://facebook.com/test{i}",
                "post_hash": post_hash,
                "scraped_at": datetime.now(timezone.utc),
            }
            
            saved = save_post_to_db(conn, test_post)
            if saved:
                saved_count += 1
            
            print(f"Variation {i}: exists_before={exists_before}, saved={saved}")
        
        # Verify only 1 post was saved
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM facebook_group_posts WHERE post_hash = %s", (post_hash,))
            count = cur.fetchone()[0]
            print(f"\nTotal posts with this hash in DB: {count}")
            assert count == 1, f"Should have exactly 1 post, found {count}"
        
        print(f"Saved count: {saved_count} (should be 1)")
        assert saved_count == 1, f"Only 1 post should be saved, but {saved_count} were saved"
        
        # Clean up test data
        with conn.cursor() as cur:
            cur.execute("DELETE FROM facebook_group_posts WHERE post_hash = %s", (post_hash,))
        conn.commit()
        print("✓ Test data cleaned up")
        
        conn.close()
        print("\n✅ Test 2 PASSED: Strict duplicate prevention works correctly")
        
    except Exception as e:
        print(f"\n❌ Test 2 FAILED: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_multiple_scraper_runs():
    """Simulate multiple scraper runs to ensure no duplicates are created."""
    print("\n" + "="*70)
    print("Test 3: Simulating multiple scraper runs")
    print("="*70)
    
    # Skip if DB credentials are not available
    if not all([DB_CONFIG["user"], DB_CONFIG["password"], DB_CONFIG["host"]]):
        print("⚠️  Skipping database tests - credentials not available")
        return
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        
        # Create test post
        test_text = f"Multi-run test post {datetime.now().isoformat()}"
        post_hash = make_post_hash(test_text)
        
        # Ensure clean slate
        if post_exists_in_db(conn, post_hash):
            with conn.cursor() as cur:
                cur.execute("DELETE FROM facebook_group_posts WHERE post_hash = %s", (post_hash,))
            conn.commit()
        
        # Simulate 5 scraper runs attempting to save the same post
        for run in range(1, 6):
            print(f"\nSimulated Run {run}:")
            
            # Check if exists (simulating the strict check in main.py)
            exists = post_exists_in_db(conn, post_hash)
            print(f"  Post exists in DB: {exists}")
            
            if exists:
                print(f"  ⟳ Skipping - post already in database")
                continue
            
            # If not exists, create and save
            test_post = {
                "post_text": test_text,
                "phone_numbers": ["01712345678"],
                "hashtags": ["#test"],
                "image_urls": {},
                "post_url": "https://facebook.com/test",
                "post_hash": post_hash,
                "scraped_at": datetime.now(timezone.utc),
            }
            
            saved = save_post_to_db(conn, test_post)
            print(f"  Saved to DB: {saved}")
        
        # Verify only 1 post exists
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM facebook_group_posts WHERE post_hash = %s", (post_hash,))
            count = cur.fetchone()[0]
            print(f"\nFinal count in DB: {count}")
            assert count == 1, f"Should have exactly 1 post after 5 runs, found {count}"
        
        # Clean up test data
        with conn.cursor() as cur:
            cur.execute("DELETE FROM facebook_group_posts WHERE post_hash = %s", (post_hash,))
        conn.commit()
        print("✓ Test data cleaned up")
        
        conn.close()
        print("\n✅ Test 3 PASSED: Multiple scraper runs handled correctly")
        
    except Exception as e:
        print(f"\n❌ Test 3 FAILED: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    print("\n" + "="*70)
    print("STRICT DUPLICATE CHECKING TESTS")
    print("="*70)
    
    try:
        test_post_exists_check()
        test_strict_duplicate_prevention()
        test_multiple_scraper_runs()
        
        print("\n" + "="*70)
        print("✅ ALL TESTS PASSED!")
        print("="*70)
        print("\nStrict duplicate checking is working correctly.")
        print("No duplicate posts will be saved to the database.\n")
        
    except Exception as e:
        print("\n" + "="*70)
        print("❌ TESTS FAILED")
        print("="*70)
        import sys
        sys.exit(1)
