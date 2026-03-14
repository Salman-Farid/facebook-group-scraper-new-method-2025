"""
supabase_setup.py
-----------------
Run this script ONCE to create the facebook_group_posts table in your
Supabase (PostgreSQL) database before using the scraper.

Usage:
    python supabase_setup.py
"""

import psycopg2
import os

DB_CONFIG = {
    "user": os.getenv("SUPABASE_DB_USER", "postgres.csnwnuxoqzwqsdlpohjg"),
    "password": os.getenv("SUPABASE_DB_PASSWORD", "?8HZ@CN/3MVwi2$"),
    "host": os.getenv("SUPABASE_DB_HOST", "aws-1-ap-northeast-2.pooler.supabase.com"),
    "port": int(os.getenv("SUPABASE_DB_PORT", "5432")),
    "dbname": os.getenv("SUPABASE_DB_NAME", "postgres"),
}


DDL = """
CREATE TABLE IF NOT EXISTS facebook_group_posts (
    id            BIGSERIAL PRIMARY KEY,
    post_text     TEXT,
    phone_numbers TEXT[],
    hashtags      TEXT[],
    image_urls    JSONB,
    post_url      TEXT,
    post_hash     TEXT UNIQUE NOT NULL,
    scraped_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index for fast duplicate detection
CREATE UNIQUE INDEX IF NOT EXISTS idx_post_hash
    ON facebook_group_posts (post_hash);

-- Index for querying by group URL prefix
CREATE INDEX IF NOT EXISTS idx_post_url
    ON facebook_group_posts (post_url);
"""

if __name__ == "__main__":
    print("🔌 Connecting to Supabase…")
    conn = psycopg2.connect(**DB_CONFIG)
    print("✅ Connected.")

    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()
    conn.close()

    print("✅ Table 'facebook_group_posts' and indexes created (or already exist).")
