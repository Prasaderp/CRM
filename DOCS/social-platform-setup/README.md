# Social platform setup

Read this page first. It covers the parts that are identical on all four
platforms: the link you send people to, and how to test it. The four platform
guides then cover only what is specific to that platform.

- [facebook-setup.md](./facebook-setup.md)
- [instagram-setup.md](./instagram-setup.md)
- [tiktok-setup.md](./tiktok-setup.md)
- [x-setup.md](./x-setup.md)

**Checked against the platforms on 7 August 2026.** Ad platforms rename buttons
and move menus often. Where a label has moved, the surrounding step still holds —
confirm the exact wording in your own account.

## How each platform reaches the CRM today

Every platform uses the same route: the ad or post carries a link, the link opens
the property page on the client's website, and the CRM takes it from there.

| Platform | How the link is delivered | Notes |
|---|---|---|
| Facebook | Link in a Page post, or the destination URL of a Traffic ad | The most direct of the four |
| Instagram | Ad destination URL, Story link sticker, or the profile bio link | Captions and Reel descriptions are not clickable |
| TikTok | Ad destination URL | Not usable from India — see the TikTok guide |
| X | Link in a post, or a Website Traffic ad | X rewrites every link through `t.co` |

None of these platforms sends leads into the CRM by itself. Forms hosted inside
Facebook, Instagram, or TikTok are a separate piece of work that has not been
built; see [native-lead-forms.md](../native-lead-forms.md).

## Before you build any link

- The site is deployed on an approved HTTPS domain, and `/p/<slug>` opens.
- The property exists in the database with an active slug.
- `RECIPIENT_ALLOW_LIST` holds the mailboxes that should receive enquiries.
  Every accepted enquiry is emailed to every address in that list.
- The published privacy notice is live, and the form's notice version matches it.
- [go-live-checklist.md](../go-live-checklist.md) is complete.

## The link

One link per platform, per campaign, per creative:

```text
https://<your-domain>/p/<property-slug>
  ?utm_source=facebook
  &utm_medium=paid_social
  &utm_campaign=fb-emerald-heights-2026q3
  &utm_content=fb-feed-video-a
```

### Rules the software actually enforces

| Parameter | Rule |
|---|---|
| `utm_source` | Must be exactly `facebook`, `instagram`, `tiktok`, or `x`. The server lowercases it. Any other value is recorded as `unknown`. Max 100 characters |
| `utm_medium` | Free text, max 100 characters. Use `paid_social` for ads and `social` for organic posts so reports stay comparable |
| `utm_campaign` | Free text, max 200 characters |
| `utm_content` | Free text, max 200 characters |
| `fbclid`, `ttclid`, `twclid` | Added by the platform, not by you. The form keeps the first one it finds, in that order, up to 512 characters |

Two things follow from this and both matter:

**One `utm_source` per link means one platform per ad.** If a single ad runs on
both Facebook and Instagram placements, every click is labelled with whichever
source you typed. Split the campaign and use one link per platform.

**Everything in the link is untrusted text.** It is stored for reporting and
nothing else. It cannot choose which property is shown, who receives the email,
or what anyone is allowed to see. A click ID identifies a click, not a person.

### Naming

Pick campaign and creative keys once and keep them, even if someone later renames
the campaign in the ad account. Use lowercase words and hyphens:

```text
utm_campaign = fb-emerald-heights-2026q3
utm_content  = fb-feed-video-a
```

Never put a person's name, email address, phone number, budget, address, account
ID, or token in a link. These values are stored and appear in reports.

### Redirects

Link directly to the property page. Do not use a URL shortener and do not add a
redirect of your own — each hop is somewhere the parameters can be dropped.

Two exceptions are unavoidable: X wraps every link in `t.co`, and your own site
may have one canonical HTTPS redirect (for example `www` to bare domain). Both
are acceptable if you test that the parameters survive.

The CRM stores the landing page and referrer as domain plus path only. Query
strings are stripped from those two fields, so a UTM value cannot leak into them.

## Test the link before you spend money

Do this on a real phone, from the ad preview if the ad exists.

1. Open the finished link. Confirm HTTPS, the correct domain, and that the
   correct property loads — not the "Property unavailable" page.
2. Confirm the address bar still shows all four `utm_` values after the page has
   loaded.
3. Submit one test enquiry with obviously fake details.
4. Confirm the page shows a reference in the form `RE-XXXXXXXXXX`.
5. Confirm the enquiry appears in `/crm/inquiries` with the expected source, and
   that the four `utm_` values are recorded against it.
6. Confirm every mailbox in `RECIPIENT_ALLOW_LIST` received the notification.
7. Submit the same form twice in a row on a bad connection. The second attempt
   must return the same reference, not create a second enquiry.
8. Check the page is usable at a 320-pixel width and at 200% zoom.
9. Delete the test enquiry according to your test-data policy.

If step 5 shows the source as `unknown`, `utm_source` is misspelled. It has to be
one of the four exact lowercase words.

## After launch

Watch these for the first few days:

- Ad spend and delivery status, so a rejection does not go unnoticed.
- Enquiries arriving with the expected source and campaign key.
- Dead jobs in the email outbox.
- Complaints or privacy requests reaching the published contact address.

Pause the campaign immediately if the property page fails to load, the form stops
accepting submissions, enquiries stop arriving, or the ad and the page no longer
say the same thing.

Ad-platform click counts and CRM enquiry counts will never match exactly. Clicks
include bounces, duplicates, and bots. Treat them as separate numbers.

## Keep a record of each launch

One short record per launch, stored wherever the client keeps business records —
not in this repository:

- The exact link, and a screenshot of the final ad preview.
- Campaign and ad names, and the ad account they were created in.
- Who approved the copy, images, and budget, and on what date.
- The property's registration details as shown on the page.
- The result of the link test above.
- Who can pause the campaign, and how to reach them.

Recheck this whenever the property, creative, link, market, or account access
changes, and at least every three months.
