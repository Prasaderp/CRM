# In-app lead forms

Facebook, Instagram, and TikTok can host the enquiry form inside their own app,
pre-filled from the user's profile. These are called Instant Forms on Meta and
Instant Forms on TikTok. They convert better than a website form because nobody
has to leave the app or type anything.

**None of this is built.** If someone switches on an Instant Form in an ad
account today, the leads collect inside Meta or TikTok and the client's inbox
stays empty. Until then, ads must send people to the property page.

This document explains what building it would actually involve, so the decision
can be made on facts rather than on how easy the ad platform makes it look.

**Verified 7 August 2026.** API versions and permission names change; recheck
before writing code.

## 1. What changes in the system

The website path is a browser posting to our own API. An in-app form is the
opposite: a third party pushes data at us, whenever it likes, and we have to
prove it is really them.

That means new components rather than a new field on an existing one:

| New piece | Why |
|---|---|
| A public webhook endpoint per platform | The platform calls us, unauthenticated except by a signature |
| Raw event storage | Store what arrived, verify it, and acknowledge in milliseconds. The platform retries if you are slow |
| A retrieval worker | The webhook carries an ID, not the lead. The lead is fetched afterwards over the platform's API |
| Credential storage with rotation | Long-lived platform tokens that expire, get revoked, and must never appear in a log |
| A field mapping per form | Each form has its own questions. There is no universal schema |
| A quarantine table | Anything that arrives unmapped, unverified, or malformed goes here, not into the CRM |
| A reconciliation job | Webhooks are missed. Something must notice and backfill |

The two rules that keep this safe are the same ones the website path already
follows: nothing in the incoming payload may decide who receives an email or
which property an enquiry belongs to, and the lead is stored durably before any
email is attempted.

## 2. Requirements common to both platforms

Complete these regardless of which platform is first.

**Ownership and access.** The client's business owns the Page or advertiser
account, the app, and the form. A developer holds access, not ownership. Record
who granted what and when.

**Credentials.** Platform tokens live in a secrets store, not in `.env` files or
the repository. Write down how each one is rotated, what happens when it expires,
and how to revoke it if a laptop is lost.

**Idempotency.** Both platforms retry. Every lead needs a natural key that makes
a repeat delivery a no-op — a unique constraint, not an application check.

**Field mapping.** Map each form question to a CRM field explicitly, keyed by the
form it came from. Store the raw answers as well. An unmapped question is a
quarantine event, not a silent drop, because someone editing the form in the ad
account will otherwise break ingestion without knowing.

**Consent.** The consent text lives in the platform's form, not in our code, and
the platform requires a privacy policy URL on it. Snapshot the notice version and
the answers with each lead, exactly as the website path does. Verify what the
form actually says before it runs.

**Retention and deletion.** Decide how long leads stay in the platform, how long
in the CRM, and how a deletion request is honoured in both.

**Fixtures before code.** Capture real request bodies from a test form — the
verification handshake, a signed notification, a successful retrieval, and each
error shape — and build the tests from those. Do not write an integration against
documentation alone; the payloads differ from the examples.

**Recovery.** Know how to export leads manually from the ad platform, because you
will need it the first time the webhook is misconfigured. Both platforms keep
lead data for a limited period, so a missed integration eventually means lost
leads, not just delayed ones.

## 3. Meta (Facebook and Instagram)

Both platforms use one integration. A Facebook Instant Form and an Instagram
Instant Form arrive through the same webhook and are read through the same API.

### Current version

Graph API **v26.0**, released 29 July 2026. v25.0 was released 18 February 2026
and expires 29 July 2028. Meta ships three to four versions a year and each lives
about two years. Pin one version explicitly, record its expiry, and plan the
upgrade — an unpinned integration breaks on Meta's schedule, not yours.

### Permissions

Reading leads with ad-level detail requires `ads_management`,
`leads_retrieval`, `pages_show_list`, `pages_read_engagement`, and
`pages_manage_ads`. These need Advanced Access, which means App Review and
business verification. Budget real time for this — it is usually the longest part
of the project, and it is not a code task.

### Webhook verification

Meta verifies the callback URL once with a `GET` carrying `hub.mode=subscribe`,
`hub.challenge`, and `hub.verify_token`. Check the verify token against your
configured value, then echo back the challenge value.

Every later delivery is a `POST` signed with
`X-Hub-Signature-256: sha256=<hex>`. Compute HMAC-SHA256 over the **raw request
body** using the app secret and compare in constant time. Two details cause most
bugs here: the signature is over the exact bytes received, so any JSON
reserialisation before verification invalidates it, and an unverified request
must be rejected before it touches any storage other than quarantine.

### What arrives, and what you do with it

The `leadgen` webhook field carries `leadgen_id`, `page_id`, `form_id`,
`adgroup_id`, `ad_id`, and `created_time` — identifiers only, no answers.

Retrieve the lead with `GET https://graph.facebook.com/v26.0/<LEAD_ID>` using a
long-lived Page access token, requested by someone with advertiser privileges on
the ad account.

Design notes:

- Use `(page_id, leadgen_id)` as the uniqueness key.
- Map fields by `(page_id, form_id, field_key)`. The same question in two forms
  is not the same field.
- Meta's rate limit is calculated from the number of leads created in the past 90
  days, so a new Page has a small allowance. Retrieval must back off rather than
  hammer.
- Acknowledge the webhook immediately and retrieve asynchronously. Retrieval
  failures retry from stored state; they do not lose the notification.

## 4. TikTok

TikTok's Instant Forms follow the same shape — subscribe to lead webhooks through
the TikTok API for Business, then retrieve the lead.

**This is not usable for a client in India.** TikTok is blocked there; see
[social-platform-setup/tiktok-setup.md](./social-platform-setup/tiktok-setup.md).

### Webhook verification

TikTok signs with a `TikTok-Signature` header whose value contains a timestamp
and a signature, in the form `t=<unix-timestamp>,s=<hex-signature>`. Split on the
comma, verify the signature, then check the timestamp is recent and reject stale
payloads — that check is what stops a captured request being replayed later.

### Verification limits

TikTok's developer portal and advertiser help centre could not be reached from
the network used to write this document, which is consistent with the Indian
block. The signature format above comes from indexed copies of TikTok's webhook
verification documentation and **has not been confirmed against a live TikTok
page**. Anyone implementing this must read the current documentation from a
market where TikTok is available, and capture real fixtures, before writing code.

The same applies to TikTok's lead retention window in Ads Manager, its permission
model, and its retrieval endpoints. Treat none of it as settled here.

## 5. X

X has no in-app lead form product to integrate with in the way Meta and TikTok
do. On X, the property page is the only route to the CRM. No work is planned.

## 6. The decision

In-app forms are not scheduled. The website path works, it is fully controlled,
and it produces leads that arrive with the consent record the client needs.

Build the Meta integration when all of these are true:

1. Ads are running profitably and the website form's drop-off rate is the
   measured bottleneck.
2. The client's business owns the Page, ad account, and app, with a named person
   able to complete App Review and business verification.
3. There is time for the review process — it is measured in weeks and cannot be
   rushed by writing code faster.
4. Someone owns the integration afterwards: version upgrades, token rotation, and
   watching for a form edit that breaks the field mapping.

Build TikTok only if the client advertises from a market where TikTok is
available.

## Sources

- [Graph API changelog](https://developers.facebook.com/docs/graph-api/changelog/) — confirmed 7 August 2026: v26.0 current, released 29 July 2026
- [Lead Ads: retrieving leads](https://developers.facebook.com/docs/marketing-api/guides/lead-ads/retrieving/) — permissions, webhook fields, retrieval endpoint, 90-day rate-limit basis
- [Webhooks getting started](https://developers.facebook.com/docs/graph-api/webhooks/getting-started/) — verification handshake and `X-Hub-Signature-256`
- [Lead Ads webhook integration](https://developers.facebook.com/docs/marketing-api/guides/lead-ads/quickstart/webhooks-integration/)
- [Meta Lead Ads Terms](https://www.facebook.com/ads/leadgen/tos) — the advertiser remains responsible for the notice, the permission, and how leads are used
- TikTok webhook verification — unreachable at the time of writing; see section 4
