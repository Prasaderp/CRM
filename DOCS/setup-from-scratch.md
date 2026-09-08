# Setting it up from scratch

The complete sequence: from a checkout on your laptop, to a live site on the
client's domain, to a real ad that a real person can click, with the enquiry
landing in the client's inbox.

Follow it in order. Each stage depends on the one before it, and each ends with a
check you can actually run. If a check fails, fix it there — do not carry a
broken step forward, because the failure will resurface later disguised as
something else.

The other documents go deeper on individual topics. This one is the spine.

## Before you start

**What you need from the client** before Stage 3:

- A domain name they own, and access to its DNS records.
- A mailbox to send from, and the list of people who should receive enquiries.
- Property details: name, locality, price wording, and the RERA registration
number and authority link.
- Their published privacy policy, or approval to publish one.
- Access to their social media accounts — as a named user, never their password.

**Accounts you need:** GitHub (private repository), [Render](https://render.com)
for hosting, [Neon](https://neon.com) for the database.

**What it costs.** Confirm current prices before quoting the client — these move.


| Piece                     | Plan               | Why not free                                                                                                                   |
| ------------------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| Static site (the website) | Free               | —                                                                                                                              |
| Web service (the API)     | Starter, ~$7/month | Free services sleep after 15 minutes idle and take 30–60 seconds to wake. Someone clicking an ad would stare at a blank screen |
| Background worker (email) | Starter, ~$7/month | Render has no free tier for background workers                                                                                 |
| Neon database             | Launch, ~$5/month  | Explained in 2.3 — the worker polls continuously, so the free plan's compute allowance runs out mid-month                      |


Roughly $20/month. That is the honest floor for something that answers an ad
click immediately and sends email reliably.

**Rough timing:** Stage 1 an afternoon. Stage 2 two to three hours the first
time. Stages 3 and 4 depend on how fast the client responds — usually the slowest
part. Stages 5 to 7 an afternoon.

---



# Stage 1 — Run it on your own machine

Do this first even though you have already built the software. It proves your
checkout is complete and gives you a working reference to compare against when
the hosted version misbehaves.

Follow the *Run it locally* section of [README.md](./README.md): install the
dependencies, start PostgreSQL and Mailpit, apply the migrations, create a user,
insert the test property, and start the three processes.

**Check before moving on.** Open `http://127.0.0.1:5173/p/local-test-home`,
submit an enquiry with fake details, and confirm all three of these:

1. The page shows a reference like `RE-4KJ8H2M9QP`.
2. The enquiry is listed at `http://127.0.0.1:5173/crm/inquiries`.
3. The email is sitting in Mailpit at `http://127.0.0.1:8025`.

If any of the three fails, stop and fix it locally. Diagnosing the same fault
through a hosting dashboard is far slower.

Local uses `SMTP_SECURITY=none` because Mailpit speaks plain SMTP. The
application refuses to start with that value anywhere except local, so you cannot
carry it into production by accident.

---



# Stage 2 — Deploy it



## 2.1 What you are building

Four pieces. Three on Render, one on Neon.

```text
                    crm.clientdomain.com
                             │
                    ┌────────▼────────┐
                    │  Static Site    │   the built React files, on Render's CDN
                    │  (Render, free) │
                    └────────┬────────┘
                             │  /api/*  proxied by a rewrite rule
                    ┌────────▼────────┐
                    │  Web Service    │   FastAPI
                    │  (Render)       │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐        ┌──────────────────┐
                    │  Neon Postgres  │◄───────┤ Background Worker│
                    └─────────────────┘        │ (Render) — email │
                                               └──────────────────┘
```

The worker receives no web traffic. It watches the database for queued emails and
sends them. That is why it is a separate service rather than a thread inside the
API: if email is slow or broken, enquiries still get saved.

## 2.2 The rule that shapes all of it

**The browser must see one origin.** The frontend calls the API at relative paths
like `/api/v1/leads` and sends its session cookie with `same-origin` credentials.
If the browser talks to `crm.clientdomain.com` for pages and
`crm-api.onrender.com` for data, sign-in breaks and no setting fixes it.

Render solves this with a static site *rewrite rule*: requests to `/api/`* are
proxied through to the API service, so the browser only ever sees one hostname.

Two consequences to remember, because both cause confusing failures later:

- `PUBLIC_ORIGIN` must be the **static site's** domain, not the API's
`onrender.com` URL. The browser's `Origin` header carries the static site
domain, and the API rejects sign-in requests whose origin it does not
recognise.
- Render does not apply a rewrite when a real file exists at that path. This is
helpful — your JavaScript and CSS files are served directly — but it means the
rules must be ordered correctly, with `/api/*` before the catch-all.



## 2.3 Create the database

1. Create a Neon project. Choose the region closest to the client's customers.
2. Name the database `real_estate_crm`.
3. From the project dashboard, copy the connection string. Neon offers two:
  - **Direct** — `...ep-xxx.region.aws.neon.tech/...`
  - **Pooled** — the same host with `-pooler` inserted
   **Use the direct one.** The pooled endpoint exists for serverless functions
   that open a connection per request. Our services are long-lived processes that
   already maintain their own connection pool, and migrations need a direct
   connection anyway. Using the pooler here adds a failure mode for no benefit.
4. Keep the string somewhere safe. It contains the password and it is the only
  thing standing between the internet and your customer data.

**On the Neon plan.** Neon suspends a database after five minutes of inactivity
and this cannot be switched off. Our email worker checks for queued jobs every
second, so the database never goes idle and never suspends. That is correct
behaviour for a worker but it means roughly 720 hours of compute per month, well
past the free plan's allowance of 100 compute-hours. The free plan will stop
working partway through the month. Start on the paid plan.

## 2.4 Put the code on GitHub

Render deploys from a repository. Push the project to a **private** GitHub
repository — the repository contains no secrets, but it also has no reason to be
public.

Confirm `.env` is listed in `.gitignore` before you push. That file holds the
database password.

## 2.5 Create the API service

In Render, create a **Web Service** from the repository.


| Setting           | Value                                                  |
| ----------------- | ------------------------------------------------------ |
| Language          | Python 3                                               |
| Build command     | `pip install uv && uv sync --project backend --no-dev` |
| Start command     | see below                                              |
| Health check path | `/health/ready`                                        |
| Instance type     | Starter or higher                                      |


Start command:

```bash
uv run --project backend uvicorn real_estate_crm.app:app --host 0.0.0.0 --port $PORT --forwarded-allow-ips="*"
```

Each part of that line is load-bearing:

- `--host 0.0.0.0` — Render only routes traffic to a service listening on all
interfaces. Binding to `127.0.0.1` produces a service that starts cleanly and
never receives a request.
- `--port $PORT` — Render assigns the port and expects you to use it.
- `--forwarded-allow-ips="*"` — the API rate-limits form submissions per
visitor IP. Behind Render's load balancer every request appears to come from
the same address unless the forwarded headers are trusted, which would put all
visitors in one bucket and start returning `429` to real people. Render's
proxy IPs are not published, so they cannot be listed individually. See the
note at the end of this section on what that trades away.



### Environment variables

Create a Render **environment group** rather than setting these on the service
directly. The worker in 2.7 needs exactly the same values, and a group keeps them
in one place instead of two lists that drift apart.

```ini
ENVIRONMENT=production
PYTHON_VERSION=3.12.10

DATABASE_URL=<the Neon direct connection string>

PUBLIC_ORIGIN=https://crm.clientdomain.com
TRUSTED_ORIGINS=https://crm.clientdomain.com

CANONICAL_NOTICE_VERSION=2026-08-07
CANONICAL_NOTICE_TEXT=By submitting this form you agree to our privacy policy and consent to being contacted about your property enquiry.

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=leads@clientdomain.com
SMTP_PASSWORD=<the app password>
SMTP_SENDER=leads@clientdomain.com

RECIPIENT_ALLOW_LIST=agent@clientdomain.com,owner@clientdomain.com
```

Notes on the ones that bite:

- `ENVIRONMENT=production` turns on secure cookies, HTTPS enforcement, origin
checking, and mandatory SMTP authentication and encryption. The application
refuses to start without them. Do not set it to `local` to clear a startup
error — the error is telling you something real.
- `SMTP_SECURITY` must be `starttls` for port 587 or `tls` for port 465. Ask the
mail provider which they want; Google Workspace and Microsoft 365 both use 587
with STARTTLS. The application will not send credentials over an unencrypted
connection, so getting this wrong fails loudly at the first email rather than
silently leaking a password.
- `SMTP_PASSWORD` must be an **app password** generated for this purpose, not the
mailbox owner's login password. Ask the client to generate one; it can be
revoked without changing their own sign-in.
- `PUBLIC_ORIGIN` is the client's domain from 2.9, not the `onrender.com` URL.
You will set the real value in 2.10 after the domain exists.

Ask the client to confirm the sending domain has SPF, DKIM, and DMARC records.
Without them, notification emails land in spam and the client concludes the CRM
is broken.

**What** `--forwarded-allow-ips="*"` **costs you.** Trusting forwarded headers from
any source means a determined attacker can vary the address the rate limiter
sees, and so bypass the per-visitor limit of five submissions then one per
minute. The application's global limit — 60 submissions with a one-per-second
refill, shared across everyone — still applies and is not spoofable, so this
caps abuse rather than eliminating it. The alternative is a rate limiter that
breaks for legitimate visitors, which is worse. Revisit if you ever see spam
volume that the global limit does not contain.

## 2.6 Run the migrations

The database is empty. It needs its tables before anything will start.

Run this from your laptop with the environment pointed at Neon. It is a one-off
command that does not need to run on Render:

```powershell
$env:DATABASE_URL = "<the Neon direct connection string>"
uv run --project backend alembic -c backend/alembic.ini upgrade head
```

For later deploys that include a migration, set Render's **pre-deploy command**
on the API service to the same thing:

```bash
uv run --project backend alembic -c backend/alembic.ini upgrade head
```

The pre-deploy command runs after the build and before the new version goes live,
which is exactly the right moment — the schema is updated before any code that
depends on it starts serving. It is available on paid instances. If you are not
using it, run migrations by hand from your laptop *before* triggering the deploy,
never after.

## 2.7 Create the worker

Create a **Background Worker** from the same repository.


| Setting       | Value                                                                                                 |
| ------------- | ----------------------------------------------------------------------------------------------------- |
| Build command | `pip install uv && uv sync --project backend --no-dev`                                                |
| Start command | `uv run --project backend python -m real_estate_crm.notifications.worker --worker-id render-worker-1` |
| Environment   | attach the same environment group from 2.5                                                            |
| Instance type | Starter                                                                                               |


No health check path and no port — background workers receive no traffic.

Run exactly one worker for now. The job claiming is safe with several running,
but one is enough for this volume and it keeps the logs readable.

## 2.8 Create the static site

Create a **Static Site** from the same repository.


| Setting              | Value                                                                                      |
| -------------------- | ------------------------------------------------------------------------------------------ |
| Build command        | `corepack enable && pnpm install --frozen-lockfile && pnpm --dir frontend exec vite build` |
| Publish directory    | `frontend/dist`                                                                            |
| Environment variable | `NODE_VERSION=24.18.0`                                                                     |


Then add two **rewrite** rules, in this order:


| #   | Source   | Destination                                     | Action  |
| --- | -------- | ----------------------------------------------- | ------- |
| 1   | `/api/*` | `https://<your-api-service>.onrender.com/api/*` | Rewrite |
| 2   | `/*`     | `/index.html`                                   | Rewrite |


Rule 1 is what makes the API same-origin. Rule 2 is what makes deep links work:
without it, someone opening `/p/emerald-heights-2bhk` straight from an ad gets a
404 instead of the property page — and that is how every single visitor arrives.

Both must be **Rewrite**, not Redirect. A redirect changes the browser's address
bar and would send the browser to the `onrender.com` host directly, which
reintroduces the cross-origin problem rule 1 exists to solve.

## 2.9 Point the domain at the static site

1. In the static site's settings, add the custom domain
  `crm.clientdomain.com`.
2. Render shows the DNS record to create. Add it at the client's DNS provider —
  normally a `CNAME` pointing at the Render-supplied hostname.
3. Wait for Render to report the domain as verified and the certificate as
  issued. This usually takes minutes; DNS propagation can make it longer.

Use a subdomain like `crm.` rather than the client's main website domain, so this
is independent of whatever else they host.

## 2.10 Set the real origin and redeploy

Now that the domain exists, set `PUBLIC_ORIGIN` and `TRUSTED_ORIGINS` in the
environment group to `https://crm.clientdomain.com` and redeploy the API and the
worker.

Skipping this leaves the API rejecting every sign-in attempt with no obvious
explanation, because the browser's origin will not match what the API was told to
expect.

## 2.11 Check the deployment

Run these against the custom domain, not the `onrender.com` URL.

```bash
curl -sS https://crm.clientdomain.com/health/live
curl -sS https://crm.clientdomain.com/health/ready
curl -sS -o /dev/null -w "%{http_code}\n" https://crm.clientdomain.com/metrics
curl -sS -o /dev/null -w "%{http_code}\n" https://crm.clientdomain.com/p/anything-at-all
```


| Check                   | Expected                              | If it fails                                                                                           |
| ----------------------- | ------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `/health/live`          | `{"status":"live"}`                   | Rewrite rule 1 is wrong, or the API is not running                                                    |
| `/health/ready`         | `{"status":"ready","reason":"ready"}` | `database_unavailable` means `DATABASE_URL` is wrong; `migration_mismatch` means 2.6 did not complete |
| `/metrics`              | `404`                                 | Expected — that endpoint only answers locally                                                         |
| `/p/anything-at-all`    | `200`, app's own "not found" state    | Rewrite rule 2 is missing                                                                             |
| The domain in a browser | Padlock, no warning                   | Certificate not issued yet                                                                            |


`/health/live` returning JSON is the proof that the rewrite proxy works, since
that response can only have come from the API service through it.

**The one check that matters most** comes in Stage 3.4, when you sign in. That is
what proves session cookies survive the proxy. Everything up to here works
without cookies; sign-in does not. If sign-in fails with a CSRF or session error
after `PUBLIC_ORIGIN` is correct, the fallback is to serve the frontend from the
API service itself instead of as a separate static site — one origin, no proxy,
at the cost of losing the CDN.

---



# Stage 3 — Load the client's real content

The site is live but empty. Four things go in, in this order.

## 3.1 Publish the privacy notice

The client's website needs a privacy page at a public HTTPS address stating who
collects the data, why, who receives it, how long it is kept, and how to contact
them about it. Their existing one may be enough — read it and check it actually
covers enquiry data.

Then make the application agree with it. In
`frontend/src/features/lead-capture/LeadForm.tsx`, replace the test values:

```ts
export const FORM_VERSION = "property-inquiry-1.0";
export const PRIVACY_NOTICE_VERSION = "2026-08-07";
```

Set `CANONICAL_NOTICE_VERSION` in the environment group to the same value, and
`CANONICAL_NOTICE_TEXT` to the exact consent sentence shown on the form. The
server stores its own copy of that text with every enquiry, which is what proves
later what someone agreed to.

Commit and push. Render rebuilds the static site automatically.

## 3.2 Confirm who receives enquiries

Re-read `RECIPIENT_ALLOW_LIST` with the client. Enquiries contain customer names
and phone numbers, so this should be the people who genuinely need them. Changing
it means editing the environment group and redeploying the worker, so get it
right now.

## 3.3 Add the properties

Properties are created directly in the database, on purpose. Nothing in a link or
a form field can create one or change which one is shown.

Use the SQL editor in the Neon dashboard, or `psql` with the Neon connection
string:

```sql
INSERT INTO properties
  (id, slug, title, summary, locality, price_label,
   project_registration_number, registration_authority_url)
VALUES
  (gen_random_uuid(),
   'emerald-heights-2bhk',
   'Emerald Heights — 2 BHK',
   'Two-bedroom apartments with covered parking, ready for possession.',
   'Wakad, Pune',
   'Starting ₹78 lakh',
   'P52100012345',
   'https://maharera.maharashtra.gov.in/');
```

Rules the database enforces, so save yourself a rejected insert:

- `slug` must be lowercase letters, digits, and hyphens, and must start and end
with a letter or digit. It appears in the ad link, so choose it once and keep
it.
- `title` up to 160 characters, `summary` up to 2000, `locality` up to 160,
`price_label` up to 80.
- `project_registration_number` and `registration_authority_url` are what the
page displays for RERA compliance. Get these from the client in writing.

To retire a property, do not delete it — existing enquiries reference it. Set it
inactive, and its page starts showing "Property unavailable":

```sql
UPDATE properties SET is_active = false WHERE slug = 'emerald-heights-2bhk';
```

Check it worked:

```bash
curl -sS https://crm.clientdomain.com/api/v1/properties/emerald-heights-2bhk
```

Then open `https://crm.clientdomain.com/p/emerald-heights-2bhk` in a browser and
read the page as a customer would. Every claim on it must be one the client can
support.

## 3.4 Create the staff logins

Run this from your laptop with the environment pointed at Neon. The script
prompts for the password twice and never accepts it as an argument, so it stays
out of your shell history.

```powershell
$env:PYTHONPATH = "backend"
$env:DATABASE_URL = "<the Neon direct connection string>"
uv run --project backend python -m scripts.create_user owner@clientdomain.com "Client Name" admin
uv run --project backend python -m scripts.create_user agent@clientdomain.com "Sales Agent" agent
```

Run this from the repository root: `PYTHONPATH` makes the `scripts` package
importable, and the root is where `.env` is read from.

Override `DATABASE_URL` only. Leave `ENVIRONMENT` alone — your local `.env` says
`local`, and forcing it to `production` here makes the settings validator reject
your local HTTPS and SMTP values before the script gets to run. The environment
is not what protects this command.

What protects it is the prompt: the script prints the database it is about to
write to and asks you to type the name back. That is the guard against creating
an account in the wrong database when you have several connection strings open in
different terminals.

One account per person, never a shared one — the CRM records who changed each
enquiry, and a shared login makes that record worthless. Passwords must be 14 to
128 characters. Send each person their password through a channel that is not
email.

**Now sign in** at `https://crm.clientdomain.com/login`. This is the check that
proves the whole origin and cookie arrangement works. If it fails, go back to
2.11.

Sessions end after 30 minutes idle and 12 hours absolute, so expect to sign in
again during a long day. That is intended.

## 3.5 One real end-to-end test

Before any money is spent, submit one enquiry through the live site with
obviously fake details, and confirm the whole chain:

1. The page returns a reference.
2. The enquiry appears in `/crm/inquiries` with the right property.
3. The email arrives in every recipient mailbox — check spam too, and fix the
  domain records if it landed there.
4. In the Neon SQL editor,
  `SELECT state, count(*) FROM outbox_jobs GROUP BY state` shows the job as
   `completed`.

Delete the test enquiry afterwards.

If the page succeeded but no email arrived, that is the system working as
designed — the enquiry is saved and the email is queued. Check the worker's logs
in Render, and see the troubleshooting section of [README.md](./README.md).

---



# Stage 4 — Get access to the client's accounts

Ask for access as yourself. Never accept their password: it defeats their
two-factor authentication, and it makes every action untraceable.

What to request on each platform:


| Platform  | What you need                                  | How they grant it                                                             |
| --------- | ---------------------------------------------- | ----------------------------------------------------------------------------- |
| Facebook  | Access to the Page and the ad account          | Meta Business Suite → Settings → add you as a person with the specific access |
| Instagram | Their professional account linked to that Page | The link is made from the Page's settings, not Accounts Center                |
| X         | Access to the ads account                      | X Ads Manager → account access                                                |
| TikTok    | Not applicable in India                        | —                                                                             |


Alongside access, get written confirmation of: who owns the business entity
running the ads, who is authorised to approve spend, and who can pause a campaign
if something goes wrong.

If the client has no accounts yet, create them with the client present, in their
name, using their email address and their phone number for recovery. Accounts
created under a developer's personal details become a serious problem later.

The account creation steps for each platform are in
[social-platform-setup/](./social-platform-setup/README.md).

Before spending, work through [go-live-checklist.md](./go-live-checklist.md).
The RERA registration and the privacy notice matter most — those are the two that
can cause real trouble rather than just wasted budget.

---



# Stage 5 — Build the campaign links

This is the connection between the ad and the CRM. There is no integration, no
API key, no plugin. The link *is* the connection: the ad carries a URL, the URL
opens the property page, the page's form posts to the CRM.

Understanding that removes most of the confusion about how these fit together.

## 5.1 The format

```text
https://crm.clientdomain.com/p/emerald-heights-2bhk?utm_source=facebook&utm_medium=paid_social&utm_campaign=fb-emerald-2026q3&utm_content=fb-feed-video-a
```


| Part                      | What it does                                                                            |
| ------------------------- | --------------------------------------------------------------------------------------- |
| `/p/emerald-heights-2bhk` | Chooses the property. Must match the `slug` from Stage 3.3                              |
| `utm_source`              | Tells the CRM which platform. Must be exactly `facebook`, `instagram`, `tiktok`, or `x` |
| `utm_medium`              | `paid_social` for ads, `social` for organic posts                                       |
| `utm_campaign`            | Your campaign name. Keep it stable                                                      |
| `utm_content`             | Which specific ad or image. Keep it stable                                              |


Get `utm_source` wrong by even one character — `Facebook`, `fb`, `facebook.com` —
and the enquiry is recorded with source `unknown`. The server lowercases it, so
capitalisation is forgiven; spelling is not.

## 5.2 Build one per platform, per creative

One link cannot honestly serve two platforms, because it carries one
`utm_source`. Make a table before you touch any ad manager, and keep it — you
will paste from it repeatedly and you will need it again when reporting:


| Platform  | Where used       | Link                                                                                                       |
| --------- | ---------------- | ---------------------------------------------------------------------------------------------------------- |
| Facebook  | Feed ad, video A | `…?utm_source=facebook&utm_medium=paid_social&utm_campaign=fb-emerald-2026q3&utm_content=fb-feed-video-a`  |
| Instagram | Feed ad, video A | `…?utm_source=instagram&utm_medium=paid_social&utm_campaign=ig-emerald-2026q3&utm_content=ig-feed-video-a` |
| Instagram | Profile bio link | `…?utm_source=instagram&utm_medium=social&utm_campaign=ig-profile&utm_content=ig-bio`                      |
| X         | Promoted post    | `…?utm_source=x&utm_medium=paid_social&utm_campaign=x-emerald-2026q3&utm_content=x-timeline-image-a`       |


Never put a person's name, phone number, email, or budget in a link. These values
are stored and appear in reports.

## 5.3 Test each link before it goes near an ad

For every link in your table, on a real phone:

1. Open it. The right property loads over HTTPS.
2. The address bar still shows all four `utm_` values.
3. Submit a fake enquiry. You get a reference.
4. It appears in `/crm/inquiries` with the expected source and campaign name.
5. The email arrives.
6. Delete the test enquiry.

A link that fails here will fail identically inside an ad, except you will have
paid for the clicks.

---



# Stage 6 — Create the ads

Full navigation for each platform is in
[social-platform-setup/](./social-platform-setup/README.md). Read the guide for
the platform you are working on. What follows is the shape common to all of them,
so you know what you are looking for.

## 6.1 Where the link goes

In every ad manager there is one field that holds the destination. That single
field is where your CRM link goes:


| Platform             | Field                                              |
| -------------------- | -------------------------------------------------- |
| Facebook / Instagram | Ad level → **Website URL**                         |
| X                    | Ad group creative → the website card or button URL |
| TikTok               | Ad level → **Destination URL**                     |


Paste the complete link, parameters included. If the tool separately offers to
append URL parameters, leave that empty — your link already has them, and
duplicates corrupt the attribution.

## 6.2 The settings that matter for this setup

Whatever else you choose, these four have to be right:

1. **Objective: traffic.** Facebook and Instagram call it **Traffic**; X calls it
  **Website Traffic**; TikTok calls it **Traffic**. Anything optimising for
   conversions needs a tracking pixel, which is not installed.
2. **Goal: link clicks.** On X specifically, do not choose *Site Visits* — it
  requires the X Pixel and Ads Manager will send you off to configure one.
3. **One platform per campaign.** Turn off automatic placements and select only
  the platform whose link you are using. On Meta this means switching off
   Advantage+ placements in the ad set.
4. **Housing category.** If Meta offers a **Special Ad Category** selector and
  Housing applies in your market, declare it. Running housing ads without it is
   a common cause of account restrictions.



## 6.3 Before you publish

- Open the ad preview and click the button. Confirm it reaches the property page
with the parameters intact. The platform may add its own `fbclid`, `ttclid`, or
`twclid` — expected, and handled.
- Confirm the ad and the page agree on price, availability, location, and who is
selling.
- Set a small starting budget and an end date, or name who will stop it.

---



# Stage 7 — Test with a real, live ad

Everything so far was tested with previews and direct links. This stage tests the
one thing you cannot simulate: a real person clicking a real ad inside a real
app, on a phone, on mobile data.

That path has caught problems that every earlier test passed, because the in-app
browser is a genuinely different environment.

## 7.1 Set it up to be safe

Publish one ad with the smallest daily budget the platform allows, a one-day
schedule, and a narrow audience. Wait for it to pass review and start delivering
— this can take a few hours.

## 7.2 Run the test

On a phone, on mobile data rather than office Wi-Fi:

1. Scroll the platform's feed until the ad appears. Do not use the preview link —
  the point is to click the delivered ad.
2. Tap it. The property page opens in the platform's in-app browser.
3. Check the page: correct property, images loading, text readable without
  zooming, form fields reachable, padlock visible.
4. Fill in the form with obviously fake but realistic details, and submit.
5. Confirm the reference appears.



## 7.3 Confirm every stage received it


| Where              | What to confirm                                                                         |
| ------------------ | --------------------------------------------------------------------------------------- |
| The phone          | A reference was shown, in the form `RE-` plus ten characters                            |
| `/crm/inquiries`   | One enquiry, with the right property, and source matching the platform you clicked from |
| The enquiry detail | The campaign and creative names from your link                                          |
| Recipient inboxes  | The notification arrived, in the inbox rather than spam                                 |
| Neon SQL editor    | `SELECT state, count(*) FROM outbox_jobs GROUP BY state` — the job is `completed`       |


Then repeat once on the other mobile operating system. iOS Safari and Android
Chrome render forms differently, and the in-app browsers differ again.

## 7.4 What each failure means


| Symptom                                         | Cause                                                   | Fix                                                                                                                                                           |
| ----------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ad click opens a "not found" page               | The static site is not falling back to `index.html`     | Add rewrite rule 2 (2.8)                                                                                                                                      |
| The page is blank for 30–60 seconds, then loads | The API is on a free instance and went to sleep         | Move it to Starter or higher                                                                                                                                  |
| Page loads, source shows `unknown`              | `utm_source` misspelled in the ad's URL field           | Correct it in the ad and republish                                                                                                                            |
| Page loads, no campaign name recorded           | The URL was pasted without its parameters               | Repaste the complete link                                                                                                                                     |
| Form submits, no reference appears              | API down, or the rewrite rule is wrong                  | Render dashboard → API service → Logs                                                                                                                         |
| Reference appears, no enquiry in the CRM        | Cannot happen — they are one transaction                | If you see this, you are looking at a different environment                                                                                                   |
| Enquiry present, no email                       | Worker or SMTP                                          | Render dashboard → worker → Logs. `smtp_tls_unsupported` means `SMTP_SECURITY` does not match the port; `smtp_authentication` means the app password is wrong |
| Email in spam                                   | Sending domain records                                  | Fix SPF, DKIM, and DMARC with the client                                                                                                                      |
| `429` after a few submissions                   | The forwarded-IP flag is missing from the start command | Check 2.5                                                                                                                                                     |


Only after this test passes should the budget go up.

---



# Stage 8 — Running it from here



## Daily

- Do enquiries appear in the CRM and in the inbox? The client will notice this
before you do — ask them.
- Any jobs stuck in the outbox `dead` state?



## Weekly

In the Render dashboard, confirm all three services show as live and read the
recent logs for anything unexpected. Then:

```bash
curl -sS https://crm.clientdomain.com/health/ready
```

And in the Neon SQL editor:

```sql
SELECT state, count(*) FROM outbox_jobs GROUP BY state ORDER BY state;
```

Anything in `dead` needs a look at `last_error_code`. Never edit `state` or
`attempts` by hand.

## Backups

Neon keeps a continuous history and can restore the database to a point in time.
Check what retention window your plan gives you and whether it is long enough to
notice a problem — a seven-day window is no help if nobody looks for two weeks.

Restore once, into a Neon branch, and confirm the enquiry count matches. A backup
you have never restored is not a backup.

For an off-platform copy, run a dump from your laptop against the Neon connection
string and store it where the client keeps their records:

```powershell
pg_dump "<the Neon direct connection string>" --format=custom --no-owner --file crm-backup.dump
```



## Deploying a change

Push to the repository's main branch. Render rebuilds and redeploys
automatically.

If the change includes a database migration, make sure the pre-deploy command
from 2.6 is set, or run the migration by hand against Neon *before* pushing. A
deploy that starts new code against an old schema fails in ways that are tedious
to unpick.

After any deploy, check readiness:

```bash
curl -sS https://crm.clientdomain.com/health/ready
```

`migration_mismatch` means the code and schema disagree — apply the migration.

## Adding a property later

Insert the row (3.3), build the links (Stage 5), test the links (5.3), then
create the ads (Stage 6). Stages 1 to 4 are done once; that loop is the ongoing
work.

## Handing over to the client

They should be able to: sign in and read enquiries, pause a campaign, reach you
when something breaks, and access their own social accounts without you. Write
down their sign-in address, who holds which account access, who to contact, and
where the backups are. One page is enough.