# Facebook Group Content Scraper – Supabase Edition (2025)

A robust web scraping tool built with Playwright that extracts posts from Facebook groups and stores every post directly in **Supabase (PostgreSQL)** – including images, phone numbers, hashtags, and post URLs.

## 🚀 Features

- **Supabase storage**: every scraped post is persisted to the `facebook_group_posts` table instead of a local text file
- **Image extraction**: collects all CDN image URLs from each post and stores them as a JSON object in the `image_urls` column
- **Structured data**: phone numbers and hashtags are extracted automatically and stored in dedicated array columns
- **Post permalink**: the URL of each post is captured and stored in `post_url`
- **Smart deduplication**: SHA-256 hash of normalized post text prevents duplicate rows across scraping sessions
  - Text normalization handles whitespace variations, unicode differences, and case sensitivity
  - Prevents the same post from being saved multiple times during scrolling
- **Multi-language "See more"**: expands truncated posts for English, Vietnamese, German and Spanish UIs
- **Session management**: saves login state for seamless re-authentication
- **Error resilience**: robust error handling for network issues and DOM changes

## 🛠️ Technologies Used

- **Python 3.10+**
- **Playwright** – browser automation
- **psycopg2** – PostgreSQL / Supabase driver
- **Chrome** – headed mode (logged-in session)

## 📋 Prerequisites

```bash
pip install -r requirements.txt
playwright install chromium
```

## 🗄️ Database Schema

```sql
CREATE TABLE facebook_group_posts (
    id            BIGSERIAL PRIMARY KEY,
    post_text     TEXT,
    phone_numbers TEXT[],
    hashtags      TEXT[],
    image_urls    JSONB,          -- {"image_1": "https://...", "image_2": "https://..."} or {}
    post_url      TEXT,
    post_hash     TEXT UNIQUE NOT NULL,
    scraped_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 🔧 Installation & Setup

1. **Clone the repository:**
```bash
git clone <your-repo-url>
cd facebook-group-scraper
```

2. **Install dependencies:**
```bash
pip install -r requirements.txt
playwright install chromium
```

3. **Create the Supabase table (first time only):**
```bash
python supabase_setup.py
```

4. **Configure your target group** – edit `main.py`:
   - `GROUP_URL` → your Facebook group URL
   - `DESIRED_POSTS` → how many posts to collect per run
   - Update `DB_CONFIG` with your own Supabase credentials if needed

## 🚀 Usage

### Step 1 – Save a login session
```bash
python login_and_save_state.py
```
- A browser window will open; log in to Facebook manually
- Return to the terminal and press Enter to save the session to `facebook_state.json`

### Step 2 – Run the scraper
```bash
python main.py
```
- The scraper navigates to the target group, scrolls the feed, expands all "See more" buttons, and upserts each post to Supabase.
- Live progress is printed for every saved post, including image count, phone numbers found, and hashtags.

### Step 3 – Test duplicate detection (optional)
```bash
python test_duplicate_detection.py
```
- Runs unit tests to verify the duplicate detection is working correctly
- Tests various scenarios: whitespace normalization, case sensitivity, unicode handling, etc.

## ⚙️ Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DESIRED_POSTS` | Number of posts to extract per run | `50` |
| `GROUP_URL` | Target Facebook group URL | (see `main.py`) |
| `MAX_SCROLLS` | Maximum scroll attempts (safety limit) | `30` |
| `DB_CONFIG` | Supabase PostgreSQL connection settings | (see `main.py`) |

## 📊 Sample Terminal Output

```
🔌 Connecting to Supabase…
✅ Connected to Supabase.
✅ Table facebook_group_posts is ready.
🔄 Navigating to group…
📜 Scroll 1/30…
   → 12 post text elements in DOM
   ✓ Post #  1 saved │ 📷 3 image(s) │ 📞 1 phone(s) │ 🏷  2 hashtag(s)
   ✓ Post #  2 saved │ 📷 0 image(s) │ 📞 2 phone(s) │ 🏷  0 hashtag(s)
   ⟳ Post already in DB – skipped
   …
🎉 Done! 50 new post(s) saved to Supabase.
```

## 🔒 Privacy & Ethics

- **Respectful scraping**: built-in delays to avoid overwhelming servers
- **Session management**: uses saved login state to avoid repeated authentication
- **Content only**: extracts only visible post content, no private data
- **Rate limiting**: appropriate delays between scroll actions

## 🐛 Troubleshooting

1. **`FileNotFoundError: facebook_state.json`** – run `login_and_save_state.py` first
2. **`psycopg2.OperationalError`** – verify `DB_CONFIG` credentials in `main.py`
3. **Table does not exist** – run `python supabase_setup.py` to create it
4. **Duplicate posts in database** – The scraper now uses text normalization to prevent duplicates:
   - Whitespace variations (spaces, tabs, newlines) are normalized
   - Unicode characters are normalized to NFC form
   - Case differences are ignored
   - If you're still seeing duplicates, run `python test_duplicate_detection.py` to verify the fix is working
4. **"See More" not expanding** – add the button label for your locale to `SEE_MORE_TEXTS` in `main.py`
5. **No images captured** – the scraper now uses 4 independent extraction strategies
   with full debug output per post. Read the `[IMG Post#N]` log lines to see exactly
   what HTML / attributes are present, which strategy matched (or why none did), and a
   3 000-character HTML snippet is auto-dumped when all strategies fail.

### Understanding image debug logs

Every post produces a block that looks like:

```
   [IMG Post#1] 🔍 Starting multi-strategy image extraction…
   [IMG Post#1] ▶ Strategy 1 — JS <img> tag scan
   [IMG Post#1]  Found 3 <img> element(s) in DOM
   [IMG Post#1]  img[0] naturalSize=40x40 alt='…' cls='…'
   [IMG Post#1]           src        = https://…fbcdn.net/…profile_pic.jpg
   [IMG Post#1]   ↳ Skipped — too small (40x40), likely avatar/icon
   [IMG Post#1]  img[1] naturalSize=960x540 alt='Post image' cls='…'
   [IMG Post#1]           currentSrc = https://…fbcdn.net/…post_image.jpg
   [IMG Post#1]  ✅ Captured image_1: https://…fbcdn.net/…post_image.jpg
   …
   [IMG Post#1] ✅ Total unique images captured: 2
```

If **all four strategies** return nothing, the scraper automatically dumps the first
3 000 characters of the article's raw HTML so you can inspect the actual DOM structure
Facebook is rendering and adjust selectors accordingly.

## 📄 License

This project is for educational and portfolio purposes. Please respect Facebook's Terms of Service and use responsibly.

## 👨‍💻 Author

[Your Name] – Web Scraping & Automation Specialist

---

**Note**: This tool is designed for educational purposes and portfolio demonstration. Always use responsibly.
