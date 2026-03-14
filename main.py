from playwright.sync_api import sync_playwright
import time
import re
import hashlib
import html
import os
from datetime import datetime, timezone
from urllib.parse import urlparse
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

DESIRED_POSTS = 30
GROUP_URL = "https://www.facebook.com/groups/163690418301859"
STORAGE_STATE = "facebook_state.json"
MAX_SCROLLS = 30  # safety limit

# Image extraction tuning
# Images whose naturalWidth AND naturalHeight are both below this threshold
# are treated as avatars / icons and skipped.
MIN_IMAGE_DIM = 100  # pixels

# How many characters of article HTML to dump when no images are found
DEBUG_HTML_SNIPPET_LEN = 3000

# Timeout (ms) for scrolling an article element into view before scanning it
SCROLL_INTO_VIEW_TIMEOUT_MS = 2000

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


# ── URL helpers ────────────────────────────────────────────────────────────────

def _is_fbcdn_url(url: str) -> bool:
    """
    Return True only when *url* has a hostname that is, or ends with,
    'fbcdn.net'.  Using urlparse prevents a crafted path segment (e.g.
    https://evil.com/fbcdn.net/img.jpg) from passing a naive substring check.
    """
    try:
        host = urlparse(url).hostname or ""
        return host == "fbcdn.net" or host.endswith(".fbcdn.net")
    except Exception:
        return False


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
    """
    Return the nearest ancestor container for a post.
    Tries multiple strategies to find the article/post container.
    """
    try:
        # Strategy 1: Look for explicit role='article'
        article = elem.locator("xpath=ancestor::div[@role='article'][1]")
        if article.count() > 0:
            return article

        # Strategy 2: Look for data-ad-rendering-role='story' (common in Facebook feeds)
        article = elem.locator("xpath=ancestor::*[@data-ad-rendering-role='story'][1]")
        if article.count() > 0:
            return article

        # Strategy 3: Look for role='article' (case-insensitive via ancestor search)
        article = elem.locator("xpath=ancestor::*[contains(@role, 'article')][1]")
        if article.count() > 0:
            return article

        # Strategy 4: Use the element's parent container (fallback)
        # This handles cases where the element itself IS the post container
        parent = elem.locator("xpath=parent::*[1]")
        if parent.count() > 0:
            parent_html = parent.inner_html()
            # Check if parent contains significant content
            if len(parent_html) > 500:
                return parent

        return None
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


def extract_image_urls(article, post_num: int = 0, elem=None, _depth: int = 0) -> dict:
    """
    Multi-strategy image extraction.
    Tries 5 independent strategies and merges results.
    """
    urls: dict = {}
    seen: set = set()

    if article is None:
        # Recursion guard: don't go deeper than 2 levels
        if _depth >= 2:
            return urls

        # If article is None but elem exists, try to extract from elem directly
        if elem is not None:
            try:
                # Try to find story container ancestors
                potential_article = elem.locator("xpath=ancestor::*[@data-ad-rendering-role='story'][1]")
                if potential_article.count() > 0:
                    return extract_image_urls(potential_article, post_num, None, _depth + 1)

                # If no explicit story container found, use the element's parent as fallback
                parent = elem.locator("xpath=ancestor::*[1]")
                if parent.count() > 0:
                    return extract_image_urls(parent, post_num, None, _depth + 1)

            except Exception:
                pass
        return urls


    def _add(src: str) -> None:
        """Normalise, de-duplicate and register a URL."""
        src = html.unescape(src.strip().split()[0]) if src.strip() else ""
        if not src:
            return
        if not _is_fbcdn_url(src):
            return
        if src in seen:
            return
        seen.add(src)
        key = f"image_{len(urls) + 1}"
        urls[key] = src

    # ── Strategy 0: Story Message Container ────────────────────────────────
    try:
        story_info = article.evaluate(
            """
            (el) => {
                const isStoryMsg = el.getAttribute('data-ad-rendering-role') === 'story_message';
                if (!isStoryMsg) return null;
                
                const pictures = el.querySelectorAll('picture');
                const bgImages = [];
                const imgs = [];
                
                el.querySelectorAll('*').forEach(node => {
                    const bg = window.getComputedStyle(node).backgroundImage;
                    if (bg && bg.includes('fbcdn')) {
                        bgImages.push({ bg, tag: node.tagName });
                    }
                    if (node.tagName === 'IMG') {
                        imgs.push({
                            src: node.currentSrc || node.src,
                            tag: 'IMG',
                            alt: node.getAttribute('alt')
                        });
                    }
                });
                
                return {
                    isStoryMsg,
                    pictureCount: pictures.length,
                    bgImageCount: bgImages.length,
                    imgCount: imgs.length,
                    bgImages,
                    imgs
                };
            }
            """
        )

        if story_info and story_info['isStoryMsg']:
            for bg_info in story_info['bgImages']:
                match = re.search(r"url\(['\"]?([^'\"]+)['\"]?\)", bg_info['bg'])
                if match:
                    url = match.group(1)
                    _add(url)

            for img_info in story_info['imgs']:
                if img_info['src']:
                    _add(img_info['src'])
    except Exception:
        pass

    # ── Strategy 1: JS <img> tag scan ────────────────────────────────────────
    try:
        img_data = article.evaluate(
            """
            (el) => {
                const rows = [];
                el.querySelectorAll('img').forEach(img => {
                    rows.push({
                        src:         img.getAttribute('src')          || '',
                        currentSrc:  img.currentSrc                   || '',
                        dataSrc:     img.getAttribute('data-src')     || '',
                        dataOrig:    img.getAttribute('data-original')|| '',
                        naturalW:    img.naturalWidth,
                        naturalH:    img.naturalHeight,
                    });
                });
                return rows;
            }
            """
        )
        for row in img_data:
            for candidate in [
                row["currentSrc"],
                row["src"],
                row["dataSrc"],
                row["dataOrig"],
            ]:
                if candidate and _is_fbcdn_url(candidate):
                    w, h = row["naturalW"], row["naturalH"]
                    if w > 0 and h > 0 and w < MIN_IMAGE_DIM and h < MIN_IMAGE_DIM:
                        break
                    _add(candidate)
                    break
    except Exception:
        pass

    # ── Strategy 2: CSS background-image scan ────────────────────────────────
    try:
        bg_data = article.evaluate(
            r"""
            (el) => {
                const results = [];
                const walk = (node, path = '') => {
                    if (node.nodeType !== 1) return;
                    const bg = window.getComputedStyle(node).backgroundImage || '';
                    const matches = bg.match(/url\(["']?([^"')]+)["']?\)/g) || [];
                    matches.forEach(m => {
                        const inner = m.match(/url\(["']?([^"')]+)["']?\)/);
                        if (inner) {
                            results.push(inner[1]);
                        }
                    });
                    node.childNodes.forEach(child => walk(child, path + '/' + node.tagName));
                };
                walk(el);
                return results;
            }
            """
        )
        for bgurl in bg_data:
            if _is_fbcdn_url(bgurl):
                _add(bgurl)
    except Exception:
        pass

    # ── Strategy 3: data-* attribute scan ────────────────────────────────────
    _DATA_ATTRS = [
        "data-src", "data-original", "data-imgurl", "data-store",
        "data-url", "data-href", "data-placehold", "data-visualcompletion",
        "data-img-fallback",
    ]
    try:
        data_hits = article.evaluate(
            f"""
            (el) => {{
                const ATTRS = {_DATA_ATTRS};
                const rows = [];
                el.querySelectorAll('*').forEach(node => {{
                    ATTRS.forEach(attr => {{
                        const val = node.getAttribute(attr);
                        if (val && val.includes('fbcdn.net')) {{
                            rows.push(val.slice(0, 300));
                        }}
                    }});
                }});
                return rows;
            }}
            """
        )
        for hit_val in data_hits:
            _add(hit_val)
    except Exception:
        pass

    # ── Strategy 4: raw inner-HTML regex (final fallback) ────────────────────
    try:
        raw_html = article.inner_html()
        raw_hits = re.findall(
            r"https?://[^\s\"'<>\\]*fbcdn\.net[^\s\"'<>\\]*"
            r"\.(?:jpg|jpeg|png|webp|avif)[^\s\"'<>\\]*",
            raw_html,
        )
        for raw in raw_hits:
            unescaped = html.unescape(raw)
            _add(unescaped)
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
            time.sleep(3)  # extra wait so lazy-load images can fully resolve

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

                    # Log: pre-extraction info (minimal)
                    print(f"   [Post#{posts_saved + 1}] 🔍 Processing post (text length: {len(text)} chars)")
                    print(f"   [Post#{posts_saved + 1}] 📝 Text preview: {text[:100]}{'…' if len(text) > 100 else ''}")

                    article = get_ancestor_article(elem)

                    if article is None:
                        print(f"   [Post#{posts_saved + 1}] ⚠️  No article ancestor found. Inspecting elem location…")
                        elem_info = elem.evaluate(
                            """
                            (el) => {
                                return {
                                    tag: el.tagName,
                                    dataAdRole: el.getAttribute('data-ad-rendering-role'),
                                    className: el.className.slice(0, 100),
                                };
                            }
                            """
                        )
                        print(f"   [Post#{posts_saved + 1}] 📌 Element: <{elem_info['tag']}> class='{elem_info['className'][:80]}'")

                    # Scroll the article into view and pause so lazy-load images
                    # have a chance to fire their network requests and resolve
                    # their src attributes before we scan.
                    if article is not None:
                        try:
                            article.scroll_into_view_if_needed(
                                timeout=SCROLL_INTO_VIEW_TIMEOUT_MS
                            )
                            time.sleep(1)
                        except Exception:
                            pass

                    post_url = extract_post_url(article)
                    image_urls = extract_image_urls(article, post_num=posts_saved + 1, elem=elem)
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
