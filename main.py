from playwright.sync_api import sync_playwright
import time
import re
import hashlib
import os
from datetime import datetime, timezone
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

DESIRED_POSTS = 30
GROUP_URL = "https://www.facebook.com/groups/163690418301859"
STORAGE_STATE = "facebook_state.json"
MAX_SCROLLS = 30  # safety limit

# Supabase / PostgreSQL connection settings.
# Must be set in environment variables or .env file
DB_CONFIG = {
    "user": os.getenv("SUPABASE_DB_USER"),
    "password": os.getenv("SUPABASE_DB_PASSWORD"),
    "host": os.getenv("SUPABASE_DB_HOST"),
    "port": int(os.getenv("SUPABASE_DB_PORT", "5432")),
    "dbname": os.getenv("SUPABASE_DB_NAME", "postgres"),
}

# Validate required environment variables
if not DB_CONFIG["user"] or not DB_CONFIG["password"] or not DB_CONFIG["host"]:
    raise ValueError(
        "❌ Missing required Supabase credentials!\n"
        "Please set SUPABASE_DB_USER, SUPABASE_DB_PASSWORD, and SUPABASE_DB_HOST "
        "in your .env file or environment variables."
    )

# "See more" button labels across languages used by group members
SEE_MORE_TEXTS = ["See more", "Xem thêm", "Mehr anzeigen", "Ver más"]


# ── helpers ────────────────────────────────────────────────────────────────────

def extract_phone_numbers(text: str) -> list:
    """Return a deduplicated list of phone-number strings found in *text*."""
    # Matches BD (+880 / 01…) numbers as well as generic international formats
    pattern = (
        r"(?:(?:\+?880)|0)[\s\-]?(?:1[3-9])[\s\-]?\d{2}[\s\-]?\d{3}[\s\-]?\d{3}"
        r"|(?:\+?\d{1,3}[\s\-]?)?\(?\d{3,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4}"
    )
    return list(dict.fromkeys(re.findall(pattern, text)))


def extract_hashtags(text: str) -> list:
    """Return a deduplicated list of hashtag strings found in *text*."""
    return list(dict.fromkeys(re.findall(r"#\w+", text)))


def make_post_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── database helpers ───────────────────────────────────────────────────────────

def ensure_table(conn) -> None:
    """Create the facebook_group_posts table if it does not already exist."""
    ddl = """
    CREATE TABLE IF NOT EXISTS facebook_group_posts (
        id          BIGSERIAL PRIMARY KEY,
        post_text   TEXT,
        phone_numbers TEXT[],
        hashtags    TEXT[],
        image_urls  JSONB,
        post_url    TEXT,
        post_hash   TEXT UNIQUE NOT NULL,
        scraped_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """
    with conn.cursor() as cur:
        cur.execute(ddl)
    conn.commit()
    print("✅ Table facebook_group_posts is ready.")


def save_post_to_db(conn, post: dict) -> bool:
    """
    Insert a post into Supabase. Skips silently if post_hash already exists.
    Returns True when a new row was inserted, False when it was a duplicate.
    """
    sql = """
        INSERT INTO facebook_group_posts
            (post_text, phone_numbers, hashtags, image_urls, post_url, post_hash, scraped_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (post_hash) DO NOTHING
    """
    with conn.cursor() as cur:
        cur.execute(sql, (
            post["post_text"],
            post["phone_numbers"],
            post["hashtags"],
            psycopg2.extras.Json(post["image_urls"]),
            post["post_url"],
            post["post_hash"],
            post["scraped_at"],
        ))
        inserted = cur.rowcount == 1
    conn.commit()
    return inserted


# ── page-level extraction helpers ─────────────────────────────────────────────

def click_see_more_buttons(page) -> None:
    """Expand all truncated posts by clicking every visible 'See more' variant."""
    for label in SEE_MORE_TEXTS:
        try:
            buttons = page.locator(f"text='{label}'")
            for i in range(buttons.count()):
                try:
                    buttons.nth(i).click(timeout=3000)
                    time.sleep(0.2)
                except Exception:
                    pass
        except Exception:
            pass


def get_ancestor_article(elem):
    """Return the nearest ancestor <div role='article'> element or None."""
    try:
        article = elem.locator("xpath=ancestor::div[@role='article'][1]")
        return article if article.count() > 0 else None
    except Exception:
        return None


def extract_post_url(article) -> str | None:
    """Find the permalink of a post from its article container."""
    if article is None:
        return None
    try:
        # Timestamp-style links that include the post ID
        for pattern in [
            "a[href*='/groups/'][href*='/?id=']",
            "a[href*='/groups/'][href*='/posts/']",
            "a[href*='/permalink/']",
        ]:
            links = article.locator(pattern)
            if links.count() > 0:
                href = links.nth(0).get_attribute("href") or ""
                # Strip query string to get the clean permalink
                return href.split("?")[0] if "?" in href else href
    except Exception:
        pass
    return None


def extract_image_urls(article) -> dict:
    """
    Collect CDN image URLs from the post's article container.
    Returns a dict like {"image_1": "https://…", "image_2": "https://…"}.
    Returns empty dict {} if no images found.
    """
    urls: dict = {}
    if article is None:
        return urls
    # URL sub-strings that identify small profile/avatar thumbnails to skip
    _SKIP_PATTERNS = ("/t1.6435-1/", "/t1.6435-9/", "s50x50", "s60x60", "s120x120")
    try:
        imgs = article.locator("img[src*='fbcdn']")
        seen: set = set()
        idx = 1
        for i in range(imgs.count()):
            try:
                img = imgs.nth(i)
                src = img.get_attribute("src") or ""
                if not src or src in seen:
                    continue
                # Skip obvious profile/avatar thumbnails by URL pattern
                if any(pat in src for pat in _SKIP_PATTERNS):
                    continue
                # Use the image's natural pixel width (requires image to be
                # loaded in the DOM).  Falls back to the HTML width attribute,
                # then to 0 if neither is available.
                try:
                    result = img.evaluate("el => el.naturalWidth")
                    natural_width = result if isinstance(result, int) else 0
                except Exception:
                    natural_width = 0
                if natural_width == 0:
                    width_attr = img.get_attribute("width") or "0"
                    natural_width = int(width_attr) if width_attr.isdigit() else 0
                # Skip tiny images (profile pictures, icons, etc.)
                if 0 < natural_width < 200:
                    continue
                urls[f"image_{idx}"] = src
                seen.add(src)
                idx += 1
            except Exception:
                pass
    except Exception:
        pass
    return urls


# ── main scraper ───────────────────────────────────────────────────────────────

def run_scraper():
    # 1. Connect to Supabase
    print("🔌 Connecting to Supabase…")
    conn = psycopg2.connect(**DB_CONFIG)
    print("✅ Connected to Supabase.")
    ensure_table(conn)

    # 2. Launch browser with saved login session
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(storage_state=STORAGE_STATE)
        page = ctx.new_page()

        print("🔄 Navigating to group…")
        page.goto(GROUP_URL)
        time.sleep(5)  # let the feed load

        posts_saved = 0
        scrolls = 0
        processed_hashes: set = set()

        while posts_saved < DESIRED_POSTS and scrolls < MAX_SCROLLS:
            scrolls += 1
            print(f"📜 Scroll {scrolls}/{MAX_SCROLLS}…")

            # Scroll to bottom to trigger lazy-loading
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)

            # Expand truncated posts
            click_see_more_buttons(page)
            time.sleep(1)

            # Locate all post text containers
            elems = page.locator("div[data-ad-rendering-role='story_message']")
            count = elems.count()
            print(f"   → {count} post text elements in DOM")

            for i in range(count):
                if posts_saved >= DESIRED_POSTS:
                    break
                try:
                    elem = elems.nth(i)
                    text = elem.inner_text().strip()
                    if not text:
                        continue

                    post_hash = make_post_hash(text)
                    if post_hash in processed_hashes:
                        continue
                    processed_hashes.add(post_hash)

                    article = get_ancestor_article(elem)
                    post_url = extract_post_url(article)
                    image_urls = extract_image_urls(article)
                    phone_numbers = extract_phone_numbers(text)
                    hashtags = extract_hashtags(text)

                    post = {
                        "post_text": text,
                        "phone_numbers": phone_numbers,
                        "hashtags": hashtags,
                        "image_urls": image_urls,
                        "post_url": post_url,
                        "post_hash": post_hash,
                        "scraped_at": datetime.now(timezone.utc),
                    }

                    if save_post_to_db(conn, post):
                        posts_saved += 1
                        print(
                            f"   ✓ Post #{posts_saved:>3} saved │ "
                            f"📷 {len(image_urls)} image(s) │ "
                            f"📞 {len(phone_numbers)} phone(s) │ "
                            f"🏷  {len(hashtags)} hashtag(s)"
                        )
                    else:
                        print(f"   ⟳ Post already in DB – skipped")

                except Exception as e:
                    print(f"   ⚠️  Error processing element {i}: {e}")
                    continue

            if posts_saved < DESIRED_POSTS:
                time.sleep(1)

        browser.close()

    conn.close()
    print(f"\n🎉 Done! {posts_saved} new post(s) saved to Supabase.")


if __name__ == "__main__":
    run_scraper()
