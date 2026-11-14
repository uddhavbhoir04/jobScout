# jobscout user guide

Detailed setup, day-to-day use and operations. For an overview, see the [README](../README.md).

- [Running locally](#running-locally)
- [Accounts and plans](#accounts-and-plans)
- [Finding leads on LinkedIn](#finding-leads-on-linkedin)
- [Finding leads on Telegram](#finding-leads-on-telegram)
- [Email outreach](#email-outreach)
- [Command-line interface](#command-line-interface)
- [How posts are qualified](#how-posts-are-qualified)
- [Email status lifecycle](#email-status-lifecycle)
- [Maintenance](#maintenance)
- [Troubleshooting](#troubleshooting)

---

## Running locally

The app needs PostgreSQL plus two processes, each in its own terminal.

**Backend (API, port 8000)**

```powershell
cd backend
.venv\Scripts\jobscout serve
```

Wait for `API on http://127.0.0.1:8000`.

**Frontend (web UI, port 3000)**

```powershell
cd frontend
npm run dev
```

Open **http://localhost:3000**. Stop either server with `Ctrl + C`. Restart the backend after changing backend
code or `backend/.env`; the frontend reloads by itself.

The browser only ever talks to Next.js. Each backend endpoint has a route handler in `frontend/src/app/api/**`
that forwards to the private Python API with the shared `INTERNAL_API_KEY`. To run the API on another port, start
it with `jobscout serve --port 8001` and set `BACKEND_URL=http://127.0.0.1:8001` in `frontend/.env.local`.

## Accounts and plans

- Sign up at **/register**. Every user has their own LinkedIn accounts, Telegram channels, searches, posts,
  contacts and email settings; nobody else can see them. The same recruiter email can exist once per user.
- Sessions last 30 days. Passwords are stored as scrypt hashes.
- The **first** user to sign up on a fresh install takes over any data created before logins existed.

Every user has an `is_paid` flag (`false` for new sign-ups), returned by `GET /api/profile` as `is_paid` / `plan`.

| | Free | Paid |
|---|---|---|
| Telegram search, LinkedIn search, contacts, posts, CSV export | ✓ | ✓ |
| **Emails**: AI-written drafts and sending from Gmail | (hidden, API returns 403) | ✓ |
| AI post analysis while scraping (`AI_EXTRACTION=true`) | rule-based | ✓ |

Change a user's plan:

```powershell
cd backend
.venv\Scripts\jobscout user set-plan you@example.com paid     # or: free
.venv\Scripts\jobscout user list
```

## Finding leads on LinkedIn

1. **LinkedIn accounts:** connect one or more LinkedIn logins. A browser window opens so you can finish any
   OTP or CAPTCHA; the session is saved for later searches. A secondary account is safer.
2. **Scrape → LinkedIn:** choose role hashtags, date range, how many contacts to collect (max 100) and which
   accounts to use, then watch the live feed.

- **`#hiring` is always required**; you don't type it. A post must also contain **at least one** role hashtag.
- Role hashtags are searched together, e.g. `#hiring AND (#pythondeveloper OR #django)`. LinkedIn returns
  nothing for queries with more than 6 hashtags, so longer lists are split into several searches automatically,
  followed by one `#hiring AND #tag` search per tag until the target is reached.
- The target counts posts that gave you a **new** email or phone number. Posts with only a contact name, or with
  an email you already have, are saved but don't count.
- A run stops when the target is reached, when you press Stop, or when LinkedIn has no more matching posts. The
  summary says which, and lists why other posts were skipped.
- **Date presets:** last 24 hours, yesterday, day before yesterday, last 3/7/30 days, or a custom range.

## Finding leads on Telegram

**Scrape → Telegram** reads public job channels through their web preview (`https://t.me/s/<channel>`). It
needs no Telegram account, API key or browser, and it's available on the free plan.

- **Channels:** new users start with `@itreferral_jobs` and `@merntech`, which measured best in Nov 2026
  (52–71% of posts carry a recruiter email or phone). Add any public channel by name or `t.me` link. Adding a
  channel reads its last ~60 posts and shows its contact rate, posting rate and last post, so weak channels are
  easy to spot. Untick a channel to pause it.
- **Keywords:** a post must mention at least one (whole words: `react` matches "React.js", not "reactive").
  Leave empty to collect every job post that has a contact.
- **Experience range (optional):** keeps posts whose stated range overlaps yours; posts that don't state
  experience are kept.
- **Skipped automatically:** posts without an email or phone, each channel's own promo addresses, the same job
  posted in several channels, and posts that ask for a fee (likely scams).

## Email outreach

Paid plan. Everything is per user.

1. **Gmail sender:** your Gmail address and a Gmail **App Password** (Google Account → Security → 2-Step
   Verification → [App passwords](https://myaccount.google.com/apppasswords)), not your normal password. *Test
   login* checks it; *Send me a test email* sends one to yourself. The App Password is stored encrypted and never
   sent back to the browser.
2. **About you:** a few lines about your skills and goals, plus your resume (PDF or Word), which is attached to
   every email. The AI reads the resume text, including links such as LinkedIn and GitHub.
3. **Write drafts:** one email per recruiter. Open any draft to edit it, rewrite it with AI, or mark it *Don't
   send*.
4. **Send:** choose how many. Emails go out 30–90 seconds apart and never above your daily limit.

How drafts are written:

- Only facts from your resume and *About you* are used; nothing is invented.
- Your experience is worked out from the resume dates. If a post asks for more years than you have, the email
  says so honestly in one sentence, highlights your most relevant work, and offers to be considered for a more
  junior opening.
- **AI providers (LangChain):** set `LLM_MODELS` to an ordered list such as
  `google_genai:gemini-3.5-flash,google_genai:gemini-3.5-flash-lite,groq:llama-3.3-70b-versatile` and add each
  provider's key. Install extra providers with `pip install -e ".[groq]"` (or `[openai]`, `[anthropic]`,
  `[ollama]`). When a model runs out of quota the next one is used; if none is left, a plain template is used.

## Command-line interface

Run from `backend/` with the virtual environment active. With several users, add `--user you@example.com`
(or set `JOBSCOUT_USER`).

```powershell
jobscout user create -e you@example.com
jobscout user list

# LinkedIn accounts (password prompted, stored encrypted)
jobscout account add -p linkedin -e you@example.com
jobscout account login 1        # visible browser; finish OTP/CAPTCHA once, the session is saved
jobscout account list

# Search (limit = new contacts to collect, max 100)
jobscout scrape -t "#pythondeveloper,#django" -d last-7d -n 30
jobscout scrape -t "#devops" --from 2026-11-10 --to 2026-11-12 -n 50 -a 1,2
#   --date: today (last 24 hours) | yesterday | day-before-yesterday | last-3d | last-7d | last-30d

jobscout posts list -n 20
jobscout contacts list
jobscout contacts export contacts.csv

# Email
jobscout email draft
jobscout email show 3
jobscout email send --dry-run
jobscout email send -n 20
jobscout email stats
jobscout email mark 3 replied   # or bounced / drafted / skipped --reason "opted out"
```

## How posts are qualified

A LinkedIn post is saved only if all of these hold:

1. it contains `#hiring` and at least one of your role hashtags,
2. its posting time overlaps the date filter (LinkedIn shows "5h" / "1d"; "1d" means 24–48 hours ago),
3. it isn't already saved,
4. it is a hiring post (rules drop `#opentowork`-style posts; AI analysis on the paid plan),
5. it contains an **email**, a **phone number**, or a **contact name written in the text** ("DM Priya Sharma").
   The author's byline alone doesn't count; see `qualifies()` in `extract/contacts.py`.

## Email status lifecycle

`pending` → `drafted` → `sending` → `sent`

- temporary SMTP error → back to `drafted` with a later `scheduled_at`; after `MAX_SEND_ATTEMPTS` → `failed`
- recipient rejected → `failed` immediately
- contacts with only a phone or name → `skipped` (becomes `pending` if an email appears later)
- `replied` / `bounced` are set by hand

Each contact (unique email or phone) gets at most one outreach email.

## Maintenance

- **LinkedIn layout changes:** every selector lives in `backend/src/jobscout/scrapers/linkedin.py`
  (`_EXTRACT_JS`, `_EXPAND_JS`, `_LOAD_MORE`). When a search finds no posts, the page is saved to
  `backend/data/debug/` for comparison.
- **Telegram markup changes:** the regexes at the top of `backend/src/jobscout/scrapers/telegram.py`.
- **Database migrations:** `jobscout db revision -m "..."` then `jobscout db upgrade`.
- **Scheduling:** Windows Task Scheduler (or cron) can run `jobscout scrape ...` and `jobscout email send -n 20`
  daily, with the working directory set to `backend/` so `.env` is found.

## Troubleshooting

| Problem | Fix |
|---|---|
| UI says "Can't reach the backend" | `jobscout serve` isn't running or crashed; start it again |
| Every API call fails after changing `INTERNAL_API_KEY` | The value must match in `backend/.env` and `frontend/.env.local`; restart both servers |
| `address already in use` | An old server is still running on 3000/8000; stop it |
| `password authentication failed` | Check `DATABASE_URL` in `backend/.env` |
| LinkedIn search shows "No results found" | Use at least one role hashtag (`#hiring` alone returns nothing); log in again on LinkedIn accounts |
| Gmail login fails (535) | Use an App Password created for the same Google account, with 2-Step Verification on |
| Gmail connection drops before login | Antivirus or firewall email scanning is intercepting SMTP; allow Python or test on another network |
| Styles look missing after editing | Stop `npm run dev`, delete `frontend/.next`, start again |
