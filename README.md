# Olmem Outreach Agent

A low-volume, evidence-based B2B outreach service built for Vercel Python Functions.
It continuously rebuilds its approved offer catalog from `www.olmemtech.com`, researches
businesses only from their own public websites, and sends only when a deterministic gate
confirms an 80+ fit score.

## What makes this dynamic

The bot does **not** contain a hard-coded list of Olmem Tech services.

1. The catalog job first checks `OUTREACH_CATALOG_URL` for a site-owned JSON catalog.
2. If that endpoint is absent, it reads the live sitemap/internal links and extracts only
   explicit commercial offers from visible site text.
3. It saves a hash-based catalog version.
4. Every prospect score is tied to that exact version.
5. When the website changes, previously eligible prospects become `needs_rescore` and
   cannot be emailed until they match the new live catalog again.
6. Removed offers are immediately inactive. New offers automatically create new discovery
   and scoring possibilities.

The optional catalog endpoint is the strongest setup because it can be generated from the
same CMS/database records used by your Services pages. The crawler fallback works without it.

## Safety and quality gates

An email is blocked unless all of these are true:

- total fit score is at least `MIN_FIT_SCORE` (default 80);
- the selected offer exists in the current live-site catalog;
- concrete problem evidence scores at least 20/35;
- offer alignment scores at least 20/30;
- at least two evidence URLs from the prospect's own website support the match;
- a business email is visibly published on that website;
- the email is role-based by default (`info@`, `sales@`, `contact@`, and similar);
- no contradiction, no-solicitation signal, existing strong solution, or closure signal exists;
- the recipient is not suppressed and has not been contacted inside the cooldown window;
- the prospect was scored against the currently active catalog version.

The score is an evidence rubric, not a claim of statistical probability.

## Architecture

- **FastAPI on Vercel**: four small cron endpoints rather than one long worker.
- **Postgres/Neon**: catalog versions, prospects, evidence, drafts, sends, events, and suppressions.
- **OpenAI structured outputs**: catalog extraction, research summary, fit scoring, and drafting.
- **Tavily or private feed**: business website discovery. It discovers websites, not guessed emails.
- **SendGrid Mail Send API**: dedicated sending identity, direct replies to `jeff@olmemtech.com`.
- **SendGrid Event Webhook**: delivery, open, click, bounce, complaint, and unsubscribe events.
- **HMAC admin webhook**: pushes lead and engagement updates into the Olmem Tech admin.

## Important sending-domain setup

Do not send autonomous outreach through the mailbox you use for normal conversations.
Authenticate a dedicated sending subdomain or separate brand-owned sending domain in
SendGrid, for example:

- From: `Jeff at Olmem Tech <outreach@updates.olmemtech.com>`
- Reply-To: `jeff@olmemtech.com`

Configure SPF, DKIM, and DMARC for the sending identity. Start with a very low daily limit.
A separate subdomain limits operational risk, but poor recipient selection or high complaint
rates can still hurt the broader brand.

## Setup

### 1. Create the database tables

Run:

```sql
-- Execute the contents of sql/schema.sql against the same Postgres/Neon database
-- used by the website, or a separate outreach database.
```

Using the same database makes it easiest for the admin panel to read `outreach_prospects`,
`outreach_messages`, and `outreach_events` directly.

### 2. Configure environment variables

Copy `.env.example` to `.env.local` for local development. Add the same values in Vercel.
Never commit the real file.

At minimum configure:

- `DATABASE_URL`
- `CRON_SECRET`
- `TOKEN_SECRET`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `SENDGRID_API_KEY`
- `SENDING_FROM_EMAIL`
- `REPLY_TO_EMAIL=jeff@olmemtech.com`
- `BUSINESS_POSTAL_ADDRESS`
- one discovery source: `TAVILY_API_KEY` or `PROSPECT_FEED_URL`

Keep `AUTONOMOUS_SEND=false` during setup. The send job will generate previews and sync them
to the admin without emailing anyone. Change it to `true` only after domain authentication,
webhook verification, suppression handling, and sample output are verified.

### 3. Deploy to Vercel

Push this folder to GitHub and import it into Vercel. Vercel detects `app.py` through the
`[tool.vercel]` entrypoint in `pyproject.toml`. The cron schedules are in `vercel.json` and
run in UTC.

The jobs are intentionally split:

- `12:00 UTC`: rebuild live offer catalog
- `13:00 UTC`: discover business websites on weekdays
- `14:00 UTC`: research and score a small batch on weekdays
- `15:00 UTC`: preview or send eligible outreach on weekdays

Vercel attaches `Authorization: Bearer <CRON_SECRET>` to protected cron calls when the
project variable is configured.

### 4. Configure SendGrid

1. Authenticate the dedicated sending domain/subdomain.
2. Create an API key limited to Mail Send and required webhook settings.
3. Configure the Event Webhook URL:
   `https://YOUR-OUTREACH-DOMAIN/api/webhooks/sendgrid/events`
4. Enable signed webhook verification and store the public key in
   `SENDGRID_EVENT_PUBLIC_KEY`.
5. Select delivery, bounce, dropped, spam report, unsubscribe, open, and click events.

Replies are sent directly to `jeff@olmemtech.com` through the `Reply-To` header. They do not
need to pass through this bot.

### 5. Connect the Olmem Tech admin

There are two options:

**Direct database**: add an Outreach section to the admin that reads the prefixed tables.
This is the most complete option.

**Webhook**: deploy the sample in `docs/nextjs-outreach-sync-route.ts` inside the Olmem Tech
Next.js app and configure `LEAD_SYNC_URL` plus the same `LEAD_SYNC_SECRET` in both projects.
The route stores every score, preview, send, and engagement event.

## Optional dynamic catalog endpoint

Set `OUTREACH_CATALOG_URL=https://www.olmemtech.com/api/outreach-catalog` and return:

```json
{
  "catalog_version": "generated-by-your-cms-or-content-updated-at-value",
  "offers": [
    {
      "offer_key": "stable-key",
      "name": "Visible service name",
      "summary": "What the live site explicitly offers",
      "problems_solved": ["Problem explicitly supported on the site"],
      "ideal_customer_signals": ["Observable business signal"],
      "exclusion_signals": ["Signal showing it is not a fit"],
      "allowed_claims": ["Conservative website-supported claim"],
      "call_to_action": "Low-pressure action",
      "landing_url": "https://www.olmemtech.com/relevant-page",
      "evidence_urls": ["https://www.olmemtech.com/relevant-page"],
      "search_queries": ["businesses with observable relevant need"]
    }
  ]
}
```

Generate this from the same service records that render the website. Do not maintain a
second manually edited service list.

## Prospect feed contract

A private feed can replace Tavily. `PROSPECT_FEED_URL` may return either an array or:

```json
{
  "candidates": [
    {
      "company_name": "Example Company",
      "website": "https://example.com",
      "source_query": "manual approved seed",
      "source_url": "https://example.com"
    }
  ]
}
```

The feed supplies only a website seed. The bot still performs its own evidence research,
email verification, scoring, and suppression checks.

## Compliance controls

The application adds truthful sender information, a valid physical postal address,
a visible unsubscribe link, and one-click unsubscribe headers. Bounces, complaints, and
unsubscribes are added to a permanent local suppression list. Keep the business address
accurate and review the rules that apply in every country or state you contact.

This project is designed for careful, low-volume B2B outreach. It intentionally does not
support purchased lists, guessed addresses, scraping personal profiles, protected-trait
inference, deceptive subjects, or high-volume blasting.

## Admin console

A branded, password-protected web console is served by the same app at `/admin`.
Set `ADMIN_PASSWORD` in the environment to enable sign-in (if it is unset, the
console refuses all logins). The session is a stateless signed cookie (HMAC with
`TOKEN_SECRET`), so it works on serverless with no session store.

What it does:

- **Dashboard** — prospect counts by status, eligible/sent totals, active catalog,
  and one-click buttons to run any pipeline job (catalog, discover, research, send)
  on demand instead of waiting for the daily cron.
- **Prospects** — searchable/filterable list; each prospect shows its research and
  fit assessment, its email history, and two send actions: **approve & send the AI
  draft now** (bypasses the autonomous-send gate and daily limit, still respects the
  suppression list) and **send a custom message**.
- **Emails** — every drafted/sent message with status, filterable; open one to read
  the exact body that was sent.
- **Criteria** — edit the fit-score gate (minimum score and per-component minimums),
  the rubric weights (max points per dimension), and operational knobs (daily send
  limit, contact cooldown, autonomous-send on/off, named-email policy, discovery
  regions). Overrides are stored in the `outreach_settings` table and applied on the
  next research/send run. "Reset to defaults" clears the overrides.

All manual sends are recorded in `outreach_messages` exactly like automated ones.

## Local run

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --reload
```

Then manually invoke a cron route with the secret:

```powershell
Invoke-RestMethod `
  -Uri http://localhost:8000/api/cron/catalog `
  -Headers @{ Authorization = "Bearer YOUR_CRON_SECRET" }
```
