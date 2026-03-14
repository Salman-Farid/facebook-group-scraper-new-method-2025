# Facebook Group Scraper Setup Guide

## Prerequisites
- Python 3.9+
- Valid Supabase account with PostgreSQL database

## Installation

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up environment variables**:
   - Copy `.env.example` to `.env`
   - Fill in your actual Supabase credentials from your Supabase dashboard:
   
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` with your real Supabase credentials:
   ```
   SUPABASE_DB_USER=postgres.your_actual_id
   SUPABASE_DB_PASSWORD=your_actual_password
   SUPABASE_DB_HOST=aws-0-ap-northeast-2.pooler.supabase.com
   SUPABASE_DB_PORT=5432
   SUPABASE_DB_NAME=postgres
   ```

3. **First time login** (generates facebook_state.json):
   ```bash
   python login_and_save_state.py
   ```
   
4. **Run the scraper**:
   ```bash
   python main.py
   ```

## Troubleshooting

### "Tenant or user not found" error
- This means your Supabase credentials are incorrect or the database user doesn't exist
- Check your `.env` file and verify credentials from your Supabase dashboard
- Make sure `SUPABASE_DB_USER` matches exactly (it looks like: `postgres.xxxxxxxxxxxxxxxx`)

### Missing .env file
- Create a `.env` file in the root directory with your credentials
- Never commit `.env` to version control (it's in `.gitignore`)

### "Missing required Supabase credentials" error
- Make sure your `.env` file has all three required fields:
  - `SUPABASE_DB_USER`
  - `SUPABASE_DB_PASSWORD`
  - `SUPABASE_DB_HOST`

