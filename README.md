<div align="center">

# jobscout

**From hiring post to recruiter inbox, without the copy-pasting.**

jobscout finds fresh hiring posts on LinkedIn and public Telegram job channels, keeps only the ones that
include a recruiter's email or phone number, and helps you send a short, honest, personalised email to each
recruiter from your own Gmail.

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%2B-4169E1?logo=postgresql&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-2EAD33?logo=playwright&logoColor=white)
![License](https://img.shields.io/badge/license-proprietary-555555)

</div>

![Scrape page: live search of Telegram job channels](docs/screenshots/scrape.png)

## Why

Job seekers lose hours scrolling hiring posts, copying addresses and writing the same email over and over. Most
job portals hide recruiter contacts; social posts and community channels don't, but they're noisy. jobscout turns
that stream into a clean, de-duplicated list of recruiter contacts, then drafts an email for each one from your
real resume, never inventing experience.

## Features

**Find leads**
- **LinkedIn hiring posts** by role hashtag, with `#hiring` always required. Searches are combined and split
  automatically to stay within LinkedIn's query limits, with date filters from "last 24 hours" to custom ranges.
- **Public Telegram job channels** through their web preview: no Telegram account or API key. Each channel shows
  its measured contact rate; filter by keywords, date and experience range.
- **Only actionable posts are kept:** a post must contain an email, phone number or named contact. The same job
  posted in several places is saved once, channel promo addresses are ignored, and fee-asking scam posts are
  skipped.
- **Live feed:** every checked post streams in as it's processed, with the reason it was saved or skipped.

**Reach out**
- **Personal drafts from your resume:** the AI reads your uploaded resume and notes, works out your real
  experience, and writes a 110–170 word email per recruiter. If a role asks for more years than you have, it says
  so honestly and offers a more junior fit.
- **Send from your own Gmail** with an App Password: spaced 30–90 s apart, a per-user daily cap, retries for
  temporary errors, and status tracking (`drafted → sent / failed / replied / bounced`).
- **Multiple AI providers** via LangChain (Gemini, OpenAI, Anthropic, Groq, Ollama), falling back down the list
  when one hits its quota, with a plain template as the last resort.

**Manage**
- Contacts and posts tables with search and **CSV export**, plus search history.
- **Multi-user** with per-user data isolation, and free / paid plans enforced on the server.

| Contacts | Email drafts |
|---|---|
| ![Contacts](docs/screenshots/contacts.png) | ![Emails](docs/screenshots/emails.png) |

## Architecture

```mermaid
flowchart LR
    B[Browser] -->|HTTPS, session cookie| N["Next.js 16<br/>UI + route handlers<br/>(src/app/api/**)"]
    N -->|"X-Internal-Key<br/>(private network)"| A["FastAPI<br/>jobscout API"]
    A --> P[(PostgreSQL)]
    A --> J["Background jobs<br/>(live events over SSE)"]
    J --> L["LinkedIn scraper<br/>Playwright, persistent profiles"]
    J --> T["Telegram reader<br/>t.me/s public pages"]
    J --> M["Mailer<br/>Gmail SMTP"]
    J --> AI["LLM providers<br/>via LangChain"]
```

- **Backend-for-frontend:** the browser only talks to Next.js. Every backend endpoint has its own route handler,
  which checks the method and IDs, filters headers, blocks cross-site requests and attaches a server-only key.
  The Python API rejects anything without that key, so it is never exposed directly.
- **Jobs and live feed:** searches, logins, drafting and sending run as background jobs with an append-only
  event log, streamed to the UI with Server-Sent Events and resumable after a reload.
- **Pluggable sources:** each source is one scraper module plus a pipeline. LinkedIn and Telegram share contact
  extraction, de-duplication and the live-event format.

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 (App Router, route handlers), React 19, TypeScript, Tailwind CSS v4, IBM Plex |
| Backend | Python 3.11+, FastAPI, Uvicorn, SQLAlchemy 2, Alembic, Pydantic Settings, Typer CLI |
| Data | PostgreSQL (partial unique indexes keep each email and phone unique per user) |
| Scraping | Playwright (Chromium, persistent sessions), plain HTTP for Telegram previews |
| Extraction | Rule-based parsing, `phonenumbers` (E.164), optional LLM analysis |
| AI | LangChain `init_chat_model` across Gemini / OpenAI / Anthropic / Groq / Ollama |
| Email | `smtplib` with STARTTLS → SSL fallback, resume attachments (PDF/DOCX text extraction) |
| Security | scrypt password hashing, hashed session tokens, Fernet-encrypted credentials, rate limiting |

## Getting started

### Prerequisites

- Python **3.11+** (3.13 recommended), Node.js **20+**, PostgreSQL **14+**
- For email outreach: a Gmail account with 2-Step Verification and an
  [App Password](https://myaccount.google.com/apppasswords), plus a key for at least one AI provider
  (for example a free [Gemini key](https://aistudio.google.com/apikey))

### 1. Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium

cp .env.example .env           # Windows: copy .env.example .env
jobscout keygen                # paste the output into FERNET_KEY in .env
# set DATABASE_URL and INTERNAL_API_KEY in .env (see Configuration)

jobscout db create             # creates the database and runs migrations
jobscout serve                 # API on http://127.0.0.1:8000
```

### 2. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local     # set the same INTERNAL_API_KEY as the backend
npm run dev                    # http://localhost:3000
```

Open http://localhost:3000, create an account, then:
- **Scrape → Telegram** works straight away, with no extra accounts.
- **LinkedIn accounts** connects a LinkedIn login for hashtag searches.
- **Emails** (paid plan) needs `jobscout user set-plan you@example.com paid`.

See the **[user guide](docs/GUIDE.md)** for full usage, the CLI and troubleshooting.

## Configuration

Backend settings live in `backend/.env` (template: [`backend/.env.example`](backend/.env.example)).

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `FERNET_KEY` | Encrypts stored LinkedIn and Gmail passwords (`jobscout keygen`) |
| `INTERNAL_API_KEY` | Shared secret between Next.js and the API; must match `frontend/.env.local` |
| `COOKIE_SECURE` | `true` in production (HTTPS only) |
| `MAX_BROWSER_JOBS` | Browser-based jobs allowed at once across all users (default 2) |
| `GEMINI_API_KEY`, `LLM_MODELS`, `*_API_KEY` | AI providers for writing emails, in fallback order |
| `DAILY_EMAIL_CAP`, `EMAIL_MIN_DELAY`, `EMAIL_MAX_DELAY` | Default sending limits and spacing |
| `DEFAULT_PHONE_REGION` | Country for phone numbers written without a country code (e.g. `IN`) |
| `HEADLESS` | Run the LinkedIn browser hidden (`false` recommended) |

Frontend settings live in `frontend/.env.local` (template: [`frontend/.env.example`](frontend/.env.example)):
`BACKEND_URL` and `INTERNAL_API_KEY`. Both are server-only and never sent to the browser.

## Project structure

```
.
├── backend/
│   ├── src/jobscout/
│   │   ├── web/            FastAPI app, auth, email + Telegram APIs, background jobs
│   │   ├── scrapers/       linkedin.py (Playwright), telegram.py (public web preview)
│   │   ├── pipeline/       per-source search loops: filter, extract, save
│   │   ├── extract/        contacts, rules, dates, AI post analysis
│   │   ├── mailer/         drafting, Gmail SMTP sender, resume parsing, send worker
│   │   ├── security/       users and sessions, encryption, rate limiting
│   │   ├── db/             SQLAlchemy models, repository helpers
│   │   ├── migrations/     Alembic migrations
│   │   ├── llm.py          multi-provider LLM client with quota-aware fallback
│   │   └── cli.py          `jobscout` command-line interface
│   └── tests/              pytest suite (unit, API and database tests)
├── frontend/
│   └── src/
│       ├── app/            pages and one route handler per API endpoint (app/api/**)
│       ├── components/     app shell, scrape, email and auth UI, design-system primitives
│       └── lib/            API client, SSE job stream, server-side backend gateway
└── docs/                   user guide and screenshots
```

## Security

- **Private API:** the backend accepts only requests from the Next.js server (shared key, constant-time compared).
  Its OpenAPI docs are disabled.
- **Route allow-list:** explicit route handlers, ID validation, header allow-listing, request size limits and
  CSRF protection (Origin / Sec-Fetch-Site).
- **Accounts:** scrypt password hashing, random session tokens stored as SHA-256 hashes, httpOnly SameSite
  cookies, and login / sign-up rate limiting.
- **Secrets at rest:** LinkedIn passwords and Gmail App Passwords are encrypted with Fernet and never returned
  to the browser.
- **Headers:** Content Security Policy, `frame-ancestors 'none'`, `nosniff`, Referrer-Policy and
  Permissions-Policy on every page, plus HSTS in production.
- **Isolation:** every query is scoped to the signed-in user, and server-side plan checks (RBAC) gate paid
  features.

Please report vulnerabilities privately; see [SECURITY.md](SECURITY.md).

## Testing

```bash
cd backend
pytest                                   # unit tests (database tests are skipped)

# full suite: point TEST_DATABASE_URL at a scratch database (it is wiped on every run)
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/jobscout_test pytest

cd ../frontend
npm run lint && npm run typecheck
```

The backend suite covers extraction rules, date filters, LinkedIn query building, the Telegram reader and
filters, per-user isolation, plan enforcement, rate limits, the email worker (against a local SMTP server) and
LLM quota fallback. CI runs it on every push (see `.github/workflows/ci.yml`).

## Responsible use

- **Respect each platform's terms.** LinkedIn's Terms of Service prohibit automated scraping, and accounts used
  for it can be restricted. Keep volumes low, use the visible browser, and prefer a secondary account. Telegram
  support reads only public channel pages, at a polite rate.
- **Contact data is personal data.** Store only what recruiters publish so candidates can apply, honour removal
  requests, and comply with applicable law (for example India's DPDP Act, GDPR and CAN-SPAM).
- **Send fewer, better emails.** Every email includes an opt-out line, sending is capped per day, and drafts are
  meant to be reviewed before they go out.

## License

Copyright © 2026 Pranav Lande. All rights reserved.

This repository is published for viewing and evaluation only. No permission is granted to use, copy, modify or
distribute the software without prior written consent. See [LICENSE](LICENSE).
