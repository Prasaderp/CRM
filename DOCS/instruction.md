# How to set up accounts and ads (business owner)

This is the only file you start with. You are not expected to install software,
run servers, or change code. Someone technical puts the website live. You own
the business decisions, the social accounts, the ads, and the spend.

Open the other documents **only when this file says so**. Do not read the whole
`DOCS` folder.

**Do not open:** `Architecture.md`, `planphases.md`, `setup-from-scratch.md`.
Those are for the technical owner.

---

## How the software works (one picture)

```text
Person taps your ad or post
        ↓
Opens YOUR website:  https://your-domain/p/<property-slug>
        ↓
Fills the enquiry form on that page
        ↓
The CRM stores the enquiry
        ↓
Your team gets an email
        ↓
Staff read it at  https://your-domain/crm/inquiries
```

The ad platforms do not send leads into this CRM by themselves. They only send
people to your property page. If you use a form that stays inside Facebook,
Instagram, or TikTok (Instant Form / Lead form), those leads never arrive here.

---

## Who does what

| You (business) | Technical owner |
|---|---|
| Answers in `go-live-checklist.md` section 1 | Puts the site on HTTPS |
| Owns Pages, Instagram, X, ad accounts | Creates the property record (`/p/<slug>`) |
| Builds the property link (this file + social README) | Sets who receives enquiry emails |
| Creates posts and Traffic ads | Creates staff CRM logins |
| Runs the phone test before spend | Confirms the live page and mail work |
| Pauses ads if the page or form breaks | Privacy notice on the live form |

Do not start ads until the technical owner has given you a live property URL
that opens on a phone.

---

## Map — follow top to bottom

```text
  0. This file (you are here)
          ↓
  1. README.md                    what is built / what is not
          ↓
  2. go-live-checklist.md §1      write down business decisions
          ↓
  3. native-lead-forms.md         stop after “None of this is built”
          ↓
  4. WAIT                         technical owner: live /p/<slug>
          ↓
  5. go-live-checklist.md §3–4, 6, 8
                                  privacy, RERA/housing, ad vs page match, sign-off
          ↓
  6. social-platform-setup/README.md
                                  one link format + 9-step test
          ↓
  7. ONE platform file            accounts, then post, then ad
          facebook-setup.md
          instagram-setup.md      (needs Facebook Page first)
          tiktok-setup.md         STOP if you advertise in India
          x-setup.md              paid X subscription before ads
          ↓
  8. Back to social README        “Test the link before you spend money”
          ↓
  9. Small budget                 then watch the first days
```

A second platform later: repeat from step 6 with a **new** link (`utm_source`
must change). Do not reuse a Facebook link on Instagram.

---

## Stage 0 — Rules that do not change

1. One property page per listing. The URL always looks like  
   `https://<your-domain>/p/<property-slug>`  
   The home page has no form. Ads must not point at the home page.
2. One platform per ad. Facebook placements only with a Facebook link.
   Instagram placements only with an Instagram link.
3. Objective is **Traffic** (Facebook/Instagram/TikTok) or **Website Traffic**
   with goal **Link clicks** (X). Never **Leads**. Never Instant Form.
4. Do not install a Meta Pixel, TikTok Pixel, or X Pixel because Ads Manager
   asks for one. Pixels are not part of this product.
5. Do not use a URL shortener. Paste the full `https://` link.
6. You own the Page / profile / ad account. Staff get access on their own
   logins. Never share one password. Turn on two-factor authentication.

---

## Stage 1 — What the product does

Open [`README.md`](./README.md). Read through **What is built**. Stop at
**Where things are**.

You should be able to say: ads send people to our page; we store the enquiry;
email is only a notification; Instant Forms and pixels are not connected.

---

## Stage 2 — Decisions in writing

Open [`go-live-checklist.md`](./go-live-checklist.md). Complete **section 1**
only. Every item needs a written answer from the person who owns the business.

You must name:

- Legal business name, address, public phone and email (these must match the
  Page, the ads, and the property page).
- Country and state of the property, and where ads will be shown.
- Sale, rent, brokerage, or new development.
- Exact mailboxes that should receive every enquiry (every address on that
  list gets every enquiry).
- One named person who can pause ads the same day.
- How long enquiry records are kept.

Send the mailbox list to the technical owner. They put it on the server. You
cannot set it from the form or from the ad link.

**Stop.** Do not open Ads Manager yet.

---

## Stage 3 — Instant Forms (read this once)

Open [`native-lead-forms.md`](./native-lead-forms.md). Read until the sentence
**None of this is built.** Close the file.

If Meta or TikTok offers “instant form”, “lead form”, “conversion location:
Instant Forms”, or “Website and Instant Forms”, do not use it.

---

## Stage 4 — Wait for the live property page

Ask the technical owner for all of these, in writing:

| You need | Example |
|---|---|
| Public property URL | `https://crm.yourdomain.com/p/emerald-heights` |
| CRM login URL | `https://crm.yourdomain.com/login` |
| Property slug | `emerald-heights` (must match the URL) |
| Privacy notice URL and version | as shown on the live form |
| Confirmation that test mailboxes received a test enquiry | |

On a phone, open the property URL (no ad yet).

- You must see that listing and the enquiry form.
- You must **not** see “Property unavailable” or “We couldn’t load this
  property.”

If the page fails, ads will fail. Fix the site first.

---

## Stage 5 — Legal and matching copy (before any campaign)

Still in [`go-live-checklist.md`](./go-live-checklist.md):

- **Section 3** — privacy notice is public; a lawyer should confirm it for
  your market (India: DPDP dates are in that section; do not treat this
  software as legal advice).
- **Section 4** — RERA / state display rules for *this* property; housing ad
  category rules; images are yours or licensed and show this property.
- **Section 6** — ad text and the page must agree on name, price,
  availability, location, and who is selling. Call to action: request
  information, not “book now” or “get approved.”
- **Section 8** — three sign-offs: business owner, technical owner, legal
  adviser.

Sections 2 and 5 of that checklist are the technical owner’s tests. You do
not run servers to complete them; you wait until they say those items are
done.

---

## Stage 6 — Build the link

Open [`social-platform-setup/README.md`](./social-platform-setup/README.md).
Read **The link**, **Rules the software actually enforces**, **Naming**, and
**Redirects**. Skip the four platform links at the top until Stage 7.

Template (one line when you paste it; line breaks below are for reading):

```text
https://<your-domain>/p/<property-slug>?utm_source=facebook&utm_medium=paid_social&utm_campaign=<campaign-key>&utm_content=<creative-key>
```

| Piece | Rule |
|---|---|
| `utm_source` | Exactly one of: `facebook` `instagram` `tiktok` `x` (lowercase). Anything else is stored as `unknown`. |
| `utm_medium` | `paid_social` for ads. `social` for ordinary posts, bio links, Stories. |
| `utm_campaign` | Lowercase and hyphens. Same string as the campaign name in Ads Manager. Keep it even if you later rename the campaign in the UI. |
| `utm_content` | Lowercase and hyphens. Names this creative, e.g. `fb-feed-video-a`. |

Example:

```text
https://crm.example.com/p/emerald-heights?utm_source=facebook&utm_medium=paid_social&utm_campaign=fb-emerald-heights-2026q3&utm_content=fb-feed-video-a
```

Do not put names, emails, phones, budgets, or account IDs in the link.

The platform may add `fbclid`, `ttclid`, or `twclid` by itself. Leave those
alone.

**Check before Stage 7:** open this link on a phone. The property must load
and all four `utm_` values must still be in the address bar.

---

## Stage 7 — Accounts, then a post, then an ad

Choose **one** platform for the first launch. Open only that file.

| First launch | File | Read in that file |
|---|---|---|
| Facebook | [`facebook-setup.md`](./social-platform-setup/facebook-setup.md) | §1 accounts, §2 post (optional), §3 ad, §4 after launch, §5 leave alone |
| Instagram | [`instagram-setup.md`](./social-platform-setup/instagram-setup.md) | §1 where links work, §2 accounts, §3 organic, §4 ad (also Facebook guide §3), §5 after launch |
| TikTok | [`tiktok-setup.md`](./social-platform-setup/tiktok-setup.md) | **§1 first.** If you advertise in India, stop. Do not create TikTok accounts. |
| X | [`x-setup.md`](./social-platform-setup/x-setup.md) | §1 paid subscription, §2 accounts, §3 `t.co`, §4 post, §5 Website Traffic ad |

### Order inside each platform file

1. **Accounts** — client-owned. Invite the agency; do not hand over ownership.
2. **Organic post or bio** (if the file has it) — paste the Stage 6 link.
   Instagram: captions are not clickable; use bio **Links** or a Story link
   sticker. Instagram ads need the professional account linked to the
   **Facebook Page** (not Accounts Center “Add accounts”).
3. **Paid ad** — Ads Manager, not “Boost post.”
4. **After launch** in that file — phone, including the in-app browser.

### Facebook / Instagram ads (short)

Full clicks are in the platform file. These are the settings that match this
CRM:

- Objective: **Traffic**. Destination: **Website**.
- Goal: maximise **link clicks**.
- If offered: **Housing** special ad category — declare it. Do not skip it
  to keep extra targeting.
- Turn **Advantage+ placements** off. Facebook campaign: Facebook only.
  Instagram campaign: Instagram only.
- Website URL: the **complete** Stage 6 link. If Ads Manager offers extra
  URL parameters, leave them empty.
- Do not attach Instant Form, pixel, call button, WhatsApp, or Messenger as
  the destination.
- Identity: the client’s Page (Facebook) or the client’s Instagram account
  (Instagram).

### TikTok ads (only if Stage 7 did not stop you)

- Custom Mode if offered. Objective **Traffic**. Destination URL = Stage 6
  link with `utm_source=tiktok`. No pixel. No Instant Form.

### X ads

- The advertising account needs a paid verification tier first.
- Objective **Website Traffic**. Ad group goal **Link clicks**, not Site
  Visits.
- Links will show as `t.co`. That is normal. Test that the four `utm_`
  values still appear on your page.

Button labels in Ads Manager change. If a label has moved, the setting
above still has to be true. Confirm in the account.

---

## Stage 8 — Test before you spend

Return to [`social-platform-setup/README.md`](./social-platform-setup/README.md)
section **Test the link before you spend money**. Do all nine steps from a
real phone, from the **live ad preview** if the ad exists, including that
app’s in-app browser.

You are looking for:

1. HTTPS, correct domain, correct property (not “unavailable”).
2. All four `utm_` values still in the address bar.
3. One fake enquiry.
4. A reference like `RE-XXXXXXXXXX` on the thank-you page.
5. The enquiry in `/crm/inquiries` with the right source and campaign key.
6. Email in every mailbox you named in Stage 2.
7. Double submit → same reference, not two enquiries.
8. Page usable on a small phone screen.
9. Test enquiry deleted per your test-data rule.

If source is `unknown`, `utm_source` is wrong. If Instagram traffic shows as
`facebook`, you reused the Facebook link — split the campaigns.

---

## Stage 9 — First days and records

Social README **After launch** and **Keep a record of each launch**, plus
`go-live-checklist.md` **section 7**.

Watch: delivery/rejection, enquiries with the expected source, email
arriving, privacy inbox.

Pause immediately if the page fails, the form fails, enquiries stop, or the
ad no longer matches the page.

Click counts in Ads Manager and enquiry counts in the CRM will not match.
Treat them as different numbers.

Keep, outside this repository: the exact link, ad preview screenshot,
account names, who approved copy/budget, registration details shown on the
page, test result, who can pause ads.

---

## If something is wrong

Use the **Problems** table in the platform file you used. Common cases:

| What you see | Usually means |
|---|---|
| “We couldn’t load this property” | Site or API is down — technical owner |
| “Property unavailable” | Wrong slug, or listing not active — technical owner |
| CRM source `unknown` | `utm_source` not exactly `facebook` / `instagram` / `tiktok` / `x` |
| Instant Form leads missing from CRM | That path is not built. Pause. Export from Ads Manager if you already ran it |
| Form ok, email late | Enquiry is already saved. Technical owner checks the mail queue |

---

## Files in this pack (and when)

| When | File |
|---|---|
| Start | this file |
| Stage 1 | [`README.md`](./README.md) |
| Stages 2 and 5 | [`go-live-checklist.md`](./go-live-checklist.md) |
| Stage 3 | [`native-lead-forms.md`](./native-lead-forms.md) (opening only) |
| Stages 6 and 8 | [`social-platform-setup/README.md`](./social-platform-setup/README.md) |
| Stage 7 | one file under [`social-platform-setup/`](./social-platform-setup/README.md) |

Ad platforms rename menus. The destination must remain: **your property
page**, **Traffic / link clicks**, **no Instant Form**, **no pixel**.
