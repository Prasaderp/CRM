# Instagram

Read [README.md](./README.md) first — it has the link format and the link test
that this guide assumes you have done.

Instagram runs on Meta's advertising system, so paid campaigns are built in the
same Ads Manager as Facebook. What differs is organic content: Instagram allows
clickable links in far fewer places than Facebook does.

**What works today:** an Instagram ad's destination URL, a Story link sticker, or
the profile bio link carries the property link to the client's website, and the
enquiry reaches the CRM.

**What does not:** Instagram Instant Forms. Leads stay inside Meta.

## 1. Where a link can go on Instagram

This is the constraint that shapes everything else.

| Place | Clickable | Use it for |
|---|---|---|
| Ad destination URL | Yes | Paid campaigns |
| Story link sticker | Yes | One link per Story slide |
| Profile bio | Yes — up to five links | The current featured property |
| Feed post caption | **No** | Point people to the bio link |
| Reel caption | **No** | Same |
| Comments | **No** | Same |

A URL typed into a caption is plain text. People cannot tap it and will not
retype it. Plan organic Instagram content around the bio link and Stories.

## 2. Accounts

### Make the account professional

A personal account cannot be linked to a Page or advertised from. In the
Instagram app: **Settings and privacy → Account type and tools → Switch to
professional account**. Choose the business category. Add the contact email,
phone number, and address that match the property page.

### Connect it to the Facebook Page

The connection has to be the business link between the Page and the professional
account. There are two ways to make it:

**From Instagram:** profile → **Edit profile** → under **Public business
information**, tap **Page** → **Connect or create** → select the client's Page.

**From the Facebook Page:** Page **Settings** → **Linked accounts** →
**Instagram** → **Connect account**.

Do not use **Accounts Center → Add accounts** for this. That links a personal
Facebook profile to Instagram for sharing and single sign-in. It does not create
the Page-to-professional-account link that advertising needs. This trips people
up regularly.

### Confirm access

In Meta Business Suite → **Settings**, confirm the business portfolio lists the
Instagram account alongside the Page and ad account, and that the person building
the campaign has access to all three. If the Instagram account is missing here,
Ads Manager will not offer it as an ad identity.

## 3. Organic content

### Bio link

Profile → **Edit profile** → **Links** → **Add external link**. Paste the full
`https://` link with its parameters and give it a short title such as the
property name. Up to five links are supported; more than one appears as a small
menu.

Use `utm_medium=social` and a campaign key naming the placement, for example
`utm_content=ig-bio`, so bio traffic is distinguishable from ad traffic.

Update this whenever the featured property changes. A stale bio link pointing at
a sold property is the most common quiet failure on Instagram.

### Story link sticker

1. Create the Story.
2. Add the **Link** sticker and paste the full link.
3. Give the sticker readable text such as "View details".
4. Post it, then tap your own sticker to confirm the destination.

One link sticker per slide. For several properties, use several slides. Stories
expire after 24 hours — add the important ones to a Highlight so the link stays
reachable.

### Feed posts and Reels

Write the caption so it points at the bio link ("details in bio"), and keep the
bio link pointing at the property the post is about. Everything the ad or post
claims about price, availability, and location must match the property page.

## 4. Run an ad

Instagram ads are built in Meta Ads Manager. The campaign structure and settings
are the same as [facebook-setup.md](./facebook-setup.md) section 3 — read it —
with three differences:

1. **Use a different link.** `utm_source=instagram`, not `facebook`. A single ad
   cannot honestly label both.
2. **Placements:** turn off Advantage+ placements and select Instagram placements
   only — Instagram Feed, and Stories or Reels if you have creative built for
   them. Exclude Facebook, Messenger, Threads, and Audience Network.
3. **Identity:** at the ad level, select the client's Instagram account. If it is
   missing, the Page-to-account link in section 2 is not complete.

Objective is still **Traffic**, performance goal is still **maximise number of
link clicks**, and the **Housing** special ad category applies exactly as it does
on Facebook.

Instagram Feed, Stories, and Reels crop very differently. Check every retained
placement in **Ad preview** before publishing, and make sure the call to action
is not covered by the interface.

## 5. After launch

Run the link test from the live ad preview on a real phone, including Instagram's
in-app browser. Confirm the enquiry arrives with source `instagram` and the
expected campaign key, and that the email reached every recipient.

If you are also running Facebook, keep the two sets of results separate. Merging
them hides which platform actually produces enquiries.

## 6. Problems

| What you see | Cause | Fix |
|---|---|---|
| Instagram account missing from **Identity** | The professional account is not linked to the Page, or was linked through Accounts Center | Redo the connection from Page Settings → Linked accounts |
| Cannot switch to professional | Account is under 18 or restricted | Resolve on the account itself; there is no workaround |
| Bio link is not clickable | Typed into the bio text instead of the **Links** field | Use **Edit profile → Links** |
| Link sticker unavailable | The Story is a repost, or the app is out of date | Update the app; create the Story natively |
| CRM source shows `facebook` for Instagram traffic | The Facebook link was reused | Split the campaigns; use the Instagram link |
| CRM source shows `unknown` | `utm_source` misspelled | It must be exactly `instagram`, lowercase |
| Enquiries from Stories but no campaign key | The sticker link had no parameters | Rebuild the sticker link with the full parameter set |

## 7. Instant Forms

Instagram Instant Forms are the same Meta product as Facebook's, sharing the same
ad account and the same lead storage. Nothing has been built to collect them, so
leads would stay inside Meta. See [native-lead-forms.md](../native-lead-forms.md)
for what that work involves.

## Sources

- [Connect a professional Instagram account and a Facebook Page](https://www.facebook.com/business/help/connect-instagram-to-page)
- [Add or change the Facebook Page connected to your Instagram professional account](https://help.instagram.com/570895513091465)
- [Traffic objective](https://www.facebook.com/business/ads/ad-objectives/traffic) — confirmed 7 August 2026
- Multiple bio links: introduced by Meta in April 2023, [reported at launch](https://techcrunch.com/2023/04/18/instagram-takes-on-linktree-and-others-with-support-for-up-to-5-links-in-bio/), still five as of August 2026

Meta and Instagram Help Centre pages render their content with JavaScript and
could not be read by an automated check. Menu paths above reflect the current
app; confirm them on the device you are using.
