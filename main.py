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


def extract_image_urls(article, post_num: int = 0) -> dict:
    """
    Multi-strategy image extraction with comprehensive debug logging.

    Tries 4 independent strategies and merges results:
      1. JS querySelectorAll for <img> (currentSrc / src / data-src)
      2. JS computed-style scan for CSS background-image properties
      3. JS data-* attribute scan (data-src, data-original, data-imgurl, etc.)
      4. Regex scan of raw inner-HTML (final fallback)

    Only fbcdn.net URLs are accepted as genuine post images.
    Images where both naturalWidth and naturalHeight are < 100 px are
    discarded as avatars / icons (only when dimensions are available).

    Verbose per-post logs are printed so you can trace exactly which
    strategy found what, and why images might be missing.
    """
    tag = f"[IMG Post#{post_num}]"
    urls: dict = {}
    seen: set = set()

    if article is None:
        print(f"   {tag} ⚠  article element is None — skipping image extraction")
        return urls

    print(f"   {tag} 🔍 Starting multi-strategy image extraction…")

    def _add(src: str) -> None:
        """Normalise, de-duplicate and register a URL."""
        # split() handles any whitespace; takes the first token
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
        print(f"   {tag}  ✅ Captured {key}: {src[:120]}")

    # ── Strategy 1: JS <img> tag scan ────────────────────────────────────────
    print(f"   {tag} ▶ Strategy 1 — JS <img> tag scan")
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
                        alt:        (img.getAttribute('alt')      || '').slice(0, 80),
                        cls:        (img.className                || '').slice(0, 80),
                    });
                });
                return rows;
            }
            """
        )
        print(f"   {tag}  Found {len(img_data)} <img> element(s) in DOM")
        for idx, row in enumerate(img_data):
            print(
                f"   {tag}  img[{idx}] "
                f"naturalSize={row['naturalW']}x{row['naturalH']} "
                f"alt='{row['alt']}' cls='{row['cls']}'"
            )
            print(f"   {tag}           src        = {row['src'][:120] or 'EMPTY'}")
            print(f"   {tag}           currentSrc = {row['currentSrc'][:120] or 'EMPTY'}")
            print(f"   {tag}           dataSrc    = {row['dataSrc'][:120] or 'EMPTY'}")
            print(f"   {tag}           dataOrig   = {row['dataOrig'][:120] or 'EMPTY'}")
            # Prefer fully-resolved currentSrc, fall back through others
            for candidate in [
                row["currentSrc"],
                row["src"],
                row["dataSrc"],
                row["dataOrig"],
            ]:
                if candidate and _is_fbcdn_url(candidate):
                    w, h = row["naturalW"], row["naturalH"]
                    # Discard tiny images only when we have real dimension data
                    if w > 0 and h > 0 and w < MIN_IMAGE_DIM and h < MIN_IMAGE_DIM:
                        print(
                            f"   {tag}   ↳ Skipped — too small ({w}x{h}), "
                            f"likely avatar/icon"
                        )
                        break
                    _add(candidate)
                    break
            else:
                if not any(
                    _is_fbcdn_url(row[k] or "")
                    for k in ("currentSrc", "src", "dataSrc", "dataOrig")
                ):
                    print(f"   {tag}   ↳ No fbcdn.net URL found in this img element")
    except Exception as exc:
        print(f"   {tag}  Strategy 1 ERROR: {exc}")

    # ── Strategy 2: CSS background-image scan ────────────────────────────────
    print(f"   {tag} ▶ Strategy 2 — CSS background-image scan")
    try:
        bg_data = article.evaluate(
            r"""
            (el) => {
                const results = [];
                const walk = (node) => {
                    if (node.nodeType !== 1) return;
                    const bg = window.getComputedStyle(node).backgroundImage || '';
                    const matches = bg.match(/url\(["']?([^"')]+)["']?\)/g) || [];
                    matches.forEach(m => {
                        const inner = m.match(/url\(["']?([^"')]+)["']?\)/);
                        if (inner) results.push(inner[1]);
                    });
                    node.childNodes.forEach(walk);
                };
                walk(el);
                return results;
            }
            """
        )
        print(f"   {tag}  Found {len(bg_data)} background-image URL(s)")
        for bgurl in bg_data:
            if _is_fbcdn_url(bgurl):
                print(f"   {tag}   ↳ fbcdn.net background: {bgurl[:120]}")
                _add(bgurl)
            else:
                print(f"   {tag}   ↳ Ignored non-fbcdn background: {bgurl[:80]}")
    except Exception as exc:
        print(f"   {tag}  Strategy 2 ERROR: {exc}")

    # ── Strategy 3: data-* attribute scan ────────────────────────────────────
    print(f"   {tag} ▶ Strategy 3 — data-* attribute scan")
    _DATA_ATTRS = [
        "data-src",
        "data-original",
        "data-imgurl",
        "data-store",
        "data-url",
        "data-href",
        "data-placehold",
        "data-visualcompletion",
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
                            rows.push({{ attr, val: val.slice(0, 300) }});
                        }}
                    }});
                }});
                return rows;
            }}
            """
        )
        print(f"   {tag}  Found {len(data_hits)} data-* attribute hit(s)")
        for hit in data_hits:
            print(f"   {tag}   ↳ [{hit['attr']}] {hit['val'][:120]}")
            _add(hit["val"])
    except Exception as exc:
        print(f"   {tag}  Strategy 3 ERROR: {exc}")

    # ── Strategy 4: raw inner-HTML regex (final fallback) ────────────────────
    # Matches fbcdn.net URLs ending in common image formats (jpg/jpeg/png/webp/avif).
    # Backslashes are excluded from the URL character class to avoid matching
    # JSON-escaped strings as valid URL fragments.
    print(f"   {tag} ▶ Strategy 4 — raw inner-HTML regex fallback")
    try:
        raw_html = article.inner_html()
        raw_hits = re.findall(
            r"https?://[^\s\"'<>\\]*fbcdn\.net[^\s\"'<>\\]*"
            r"\.(?:jpg|jpeg|png|webp|avif)[^\s\"'<>\\]*",
            raw_html,
        )
        print(f"   {tag}  Regex found {len(raw_hits)} raw URL(s) in HTML")
        for raw in raw_hits:
            unescaped = html.unescape(raw)
            print(f"   {tag}   ↳ {unescaped[:120]}")
            _add(unescaped)
    except Exception as exc:
        print(f"   {tag}  Strategy 4 ERROR: {exc}")

    # ── Summary / diagnostic dump ─────────────────────────────────────────────
    if urls:
        print(f"   {tag} ✅ Total unique images captured: {len(urls)}")
    else:
        print(f"   {tag} ❌ No images found after all 4 strategies.")
        print(
            f"   {tag} 📄 Dumping first {DEBUG_HTML_SNIPPET_LEN} chars of "
            f"article HTML for diagnosis:"
        )
        try:
            snippet = article.inner_html()
            print("   " + "-" * 72)
            for line in snippet[:DEBUG_HTML_SNIPPET_LEN].splitlines():
                print(f"   {tag}   {line}")
            if len(snippet) > DEBUG_HTML_SNIPPET_LEN:
                print(
                    f"   {tag}   … (truncated; total length {len(snippet)} chars)"
                )
            print("   " + "-" * 72)
        except Exception as dump_exc:
            print(f"   {tag}  Could not dump HTML: {dump_exc}")

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

                    article = get_ancestor_article(elem)

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
                    image_urls = extract_image_urls(article, post_num=posts_saved + 1)
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
