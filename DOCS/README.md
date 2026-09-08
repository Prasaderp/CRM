# Real-estate lead CRM

A social-media ad or post sends someone to a property page on the client's own
website. They fill in the enquiry form. The CRM stores the enquiry and emails the
sales team. Staff read enquiries in a protected web workspace.

```text
Facebook / Instagram / TikTok / X post or ad
  → /p/<property-slug> on the client's website
  → visitor submits the enquiry form
  → PostgreSQL stores the enquiry, consent record, and an email job
  → the worker sends the email to every approved recipient
  → staff open the enquiry at /crm/inquiries
```

The database is the record. Email is only a notification. The enquiry is committed
before any email is attempted, so a mail failure can never lose a lead.

## What is built

| Capability | State |
|---|---|
| Property page and enquiry form | Built |
| Enquiry storage, consent snapshot, duplicate detection | Built |
| Campaign attribution from the link (UTMs, click IDs) | Built |
| Email notification with retries | Built |
| Staff sign-in and enquiry workspace | Built |
| Forms hosted inside Facebook, Instagram, or TikTok | Not built — see [native-lead-forms.md](./native-lead-forms.md) |
| Meta / TikTok / X advertising pixels | Not built, and off by design |

Anything marked *not built* does not send leads to the CRM. Turning on such a
feature in an ad account produces leads that sit in the ad platform and never
reach the client's inbox.

## Where things are

| I want to… | Read |
|---|---|
| I own the business / I will run the ads | [instruction.md](./instruction.md) |
| Set the whole thing up, laptop to live ad | [setup-from-scratch.md](./setup-from-scratch.md) |
| Understand the system design | [Architecture.md](./Architecture.md) |
| See how it was built, phase by phase | [planphases.md](./planphases.md) |
| Publish a post or run an ad | [social-platform-setup/](./social-platform-setup/README.md) |
| Know what must be settled before spending money | [go-live-checklist.md](./go-live-checklist.md) |
| Understand in-app lead forms | [native-lead-forms.md](./native-lead-forms.md) |
| Run the system on my machine | The rest of this page |

[setup-from-scratch.md](./setup-from-scratch.md) is the one to start with if you
are the person doing the deployment and the ad setup. It runs end to end and
sends you to the other documents where they go deeper.

## Run it locally

This runs the whole system on one computer with invented data. Nothing is exposed
to the network: PostgreSQL, the mail catcher, the API, the worker, and the web
server all bind to `127.0.0.1`.

Do not put real customer details, real mailbox passwords, or social-platform
tokens into a local environment.

### You need

- Docker Desktop with Compose
- Python 3.12.10 and `uv`
- Node.js 24.18.0 and pnpm 10.34.5
- Free ports on `127.0.0.1`: 5433, 8025, 1025, 8000, 5173

### First time

From the repository root:

```powershell
Copy-Item .env.example .env
docker compose up -d postgres mailpit
$env:UV_CACHE_DIR = Join-Path (Get-Location) ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = Join-Path (Get-Location) ".uv-python"
uv sync --project backend --all-extras --python 3.12.10
corepack prepare pnpm@10.34.5 --activate
pnpm install
uv run --project backend alembic -c backend/alembic.ini upgrade head
```

`.env.example` is a template. Keep your `.env` out of source control.

### Add a user and a property

Create one staff login:

```powershell
$env:PYTHONPATH = "backend"
uv run --project backend python -m scripts.create_user admin@example.com "Test Admin" admin
```

Run it from the repository root. `PYTHONPATH` makes the `scripts` package
importable, and the root is where `.env` is read from — run it from `backend/`
instead and the settings will come up empty.

The script prints the database it is about to write to and asks you to type the
name back — `real_estate_crm` here. That guard is what makes the same command
safe to run against a production database. Then choose a password of 8–128
characters when prompted; it is never accepted as a command-line argument.

Add one obviously fake property so a property page exists:

```powershell
docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U postgres -d real_estate_crm -c "INSERT INTO properties (id,slug,title,summary,locality,price_label,project_registration_number,registration_authority_url) VALUES ('10000000-0000-4000-8000-000000000028','local-test-home','Local Test Home','Test fixture only.','Test City','Test price','TEST-RERA-28','https://example.invalid/registration') ON CONFLICT (slug) DO NOTHING"
```

Properties are only ever created on the server. A link or form field can never
choose which property is shown or who gets emailed.

### Start it

Three terminals, from the repository root:

```powershell
uv run --project backend uvicorn real_estate_crm.app:app --host 127.0.0.1 --port 8000
```

```powershell
uv run --project backend python -m real_estate_crm.notifications.worker --worker-id local-worker-1
```

```powershell
pnpm --dir frontend exec vite --host 127.0.0.1 --port 5173
```

| Address | What it is |
|---|---|
| `http://127.0.0.1:5173/p/local-test-home` | The property page and enquiry form |
| `http://127.0.0.1:5173/crm/inquiries` | Staff workspace (sign-in required) |
| `http://127.0.0.1:8000/health/ready` | API readiness |
| `http://127.0.0.1:8025` | Mailpit — catches every local email |

Readiness returns `{"status":"ready","reason":"ready"}` only when the database is
reachable and the migrations match. It does not check SMTP, because an enquiry is
saved whether or not mail is working.

### Check it works

```powershell
$env:TEST_DATABASE_URL = "postgresql://postgres:postgrespassword@127.0.0.1:5433/real_estate_crm_test"
uv run --project backend pytest -q
pnpm --dir frontend test -- --run
pnpm --dir frontend exec playwright test
pnpm --dir frontend exec vite build
```

Then submit a test enquiry from the property page and confirm three things: the
page shows a reference like `RE-XXXXXXXXXX`, the enquiry appears in
`/crm/inquiries`, and the email arrives in Mailpit.

### Stop it

```powershell
docker compose stop
```

`docker compose down --volumes` also deletes the local database. That cannot be
undone.

## When something goes wrong

**The form succeeded but no email arrived.** That is expected behaviour, not a
failure. The enquiry is saved; the email is queued. Check the queue:

```powershell
docker compose exec -T postgres psql -X -U postgres -d real_estate_crm -c "SELECT state,count(*) FROM outbox_jobs GROUP BY state ORDER BY state"
```

| State | Meaning | What to do |
|---|---|---|
| `pending` | Waiting for its next attempt | Confirm the worker is running and Mailpit is up on port 1025 |
| `processing` | A worker holds it | Wait out the two-minute lease; a replacement worker picks up stale jobs |
| `completed` | Sent | Nothing |
| `dead` | Gave up | Read `last_error_code`; fix the cause. Never edit `state` or `attempts` by hand |

The worker retries connection failures, timeouts, and temporary SMTP `4xx`
errors, waiting longer after each failure. It stops after 12 attempts, after the
job is 24 hours old, or when the wait reaches six hours. Authentication errors
and permanent SMTP `5xx` errors are not retried.

A worker can crash after the mail server accepted a message but before the job
was marked done, which can produce one duplicate email. The stable `Message-ID`
makes that case identifiable. Exactly-once email delivery is not achievable and
is not claimed.

**Readiness says `migration_mismatch`.** Stop the API and worker, check the
Alembic heads, and apply the migration that is in the repository. Never stamp
past a migration that has not run.

**Readiness says `database_unavailable`.** PostgreSQL is down or unreachable.
Start it and wait; the form correctly refuses to report success while it is down.

**Logs.** API and worker output must contain route templates and opaque IDs only.
If you ever see a name, email address, phone number, query string, cookie, token,
or message body in a log line, treat it as a defect.

## Limits of the current release

This release is local-only and uses invented data. Real traffic additionally
needs an approved production design covering hosting, authenticated SMTP,
retention and deletion, encrypted backups, monitoring, and incident response.
[go-live-checklist.md](./go-live-checklist.md) lists what has to be settled first.
