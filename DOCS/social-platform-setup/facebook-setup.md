# Facebook

Read [README.md](./README.md) first — it has the link format and the link test
that this guide assumes you have done.

**What works today:** a Facebook post or ad carries the property link, the person
lands on the client's website, and the enquiry reaches the CRM.

**What does not:** Facebook Instant Forms. A form that opens inside Facebook
keeps its leads inside Meta. Nothing arrives in the CRM or the client's inbox.

## 1. Accounts

The client owns everything. A developer or agency gets access, never ownership —
otherwise the client loses their Page and ad history when the relationship ends.

### The Page

1. Sign in as the client and open <https://www.facebook.com/pages/create>.
2. Enter the Page name, category, and description.
3. Add the logo, cover image, public phone number and email, the office address
   or service area, and the website address.
4. Publish it and check that the business name and contact details match what the
   property page says.

### The business portfolio and ad account

1. Open [Meta Business Suite](https://business.facebook.com/) and create a
   business portfolio in the client's legal business name.
2. In **Settings**, confirm the portfolio owns both the Page and the ad account.
   If either already exists elsewhere, request access to it rather than moving
   ownership casually — transfers are hard to reverse.
3. Add each staff member with their own Facebook login and only the access they
   need. Never share one password between people.
4. Turn on two-factor authentication for everyone with admin access, and record
   two people who can recover the account.
5. In Ads Manager, finish the ad account setup and add the payment method.

## 2. Publish a post

1. Switch into the Page: select your profile picture, then **See all profiles**,
   then the Page.
2. Select the post box at the top of the Page feed.
3. Paste the property link and wait for the preview card to load.
4. Write the caption. It must agree with the property page on price,
   availability, location, and who is selling. Include the registration details
   the page shows.
5. Add your own or licensed images. Do not use stock photos of a different
   building.
6. Post it, then open the post as a visitor and click through to check the link.

For scheduled or draft posts, use **Create post** in Meta Business Suite instead.
Same content rules.

Do not cross-post a link containing `utm_source=facebook` to Instagram. Instagram
traffic would then be counted as Facebook. Use the Instagram guide and its own
link.

## 3. Run an ad

Use Ads Manager rather than the **Boost post** button. Boost hides the settings
that matter here — placement control and the destination URL.

Since February 2026, Meta has one campaign creation flow. Its AI features
(Advantage+) are switched on by default for audience, placements, and budget, and
each can be switched off individually. There is no longer a separate "manual"
campaign type to choose.

### Campaign

1. In Ads Manager, select **+ Create**.
2. Objective: **Traffic**. This optimises for link clicks and does not require a
   pixel. Do not choose **Leads** — see section 5.
3. Name the campaign with the same campaign key that is in the link.
4. **Special Ad Category:** if your account offers **Housing**, select it. It is
   required for housing ads in a growing list of countries and running without it
   is a common cause of account restrictions. It removes some targeting options
   by design; do not skip the declaration to get them back.
5. Set the budget and either an end date or a named person responsible for
   stopping it.

### Ad set

1. Name it with the market and placement.
2. Destination: **Website**.
3. Performance goal: **maximise number of link clicks**. Anything that optimises
   for conversions needs a pixel, which is not installed.
4. Set the schedule and the locations you are allowed to target. Housing ads
   restrict location targeting to a minimum radius in some markets, and postcode
   targeting may be unavailable.
5. **Placements:** turn off Advantage+ placements and select Facebook placements
   only — Facebook Feed is enough for a first campaign. Deselecting any placement
   turns Advantage+ placements off; you should see it marked as off. Exclude
   Instagram, Messenger, Threads, and Audience Network. They need their own link
   and their own review.

### Ad

1. Identity: the client's Facebook Page.
2. Choose **Create ad** for new creative, or **Use existing post** if you are
   promoting a post you have already checked.
3. Add the images or video, primary text, headline, and description.
4. **Website URL:** paste the complete link, parameters included.
5. If Ads Manager offers to append URL parameters, leave it empty. Your link
   already has them, and duplicates break attribution.
6. Do not attach a pixel, an instant form, a call button, or a WhatsApp or
   Messenger destination.
7. Open **Ad preview**, click the button, and confirm it lands on the property
   page with all four `utm_` values still present. Meta may add `fbclid` — that
   is expected and the CRM handles it.
8. Publish.

Meta reviews ads automatically. Campaign, ad set, and ad each have their own
status; check all three in the **Delivery** column.

## 4. After launch

Start with a small budget and run the link test from the live ad preview on both
an iPhone and an Android phone, including Facebook's in-app browser. That browser
is where destination problems usually appear first.

Then confirm one test enquiry arrives with source `facebook` and the expected
campaign key, and that the email reached every recipient.

## 5. Two things to leave alone for now

**The Leads objective.** Meta offers it with three conversion locations:
**Instant Forms**, **Website**, and — in some accounts — **Website and Instant
Forms**. The Website option does send people to your page, but its optimisation
depends on the Meta Pixel reporting conversions back. Without the pixel it has no
advantage over Traffic, and the Instant Form options do not reach the CRM at all.

**The Meta Pixel and Conversions API.** Neither is installed, by decision. They
measure ad performance; they do not deliver leads. Adding either means a privacy
review, a consent mechanism, and code that fires only after the CRM has durably
saved an enquiry. Do not install a pixel just because Ads Manager asks for one.

## 6. Problems

| What you see | Cause | Fix |
|---|---|---|
| The Page is missing from **Identity** | The ad account and Page are not in the same business portfolio, or you lack access | Fix the access. Do not substitute a different Page |
| Ad rejected | Open the ad and read the policy reason | Fix the actual issue. Housing ads are usually rejected for a missing category declaration or a targeting restriction |
| Instagram is getting the Facebook link | A placement or cross-post setting is on | Pause, split the platforms, use the Instagram link |
| CRM source shows `unknown` | `utm_source` is misspelled | It must be exactly `facebook`, lowercase |
| "Property unavailable" | Wrong slug, or the property is not active | Fix the property record. A link cannot override it |
| Form succeeded, no email | Normal — the enquiry is saved and the email is queued | Check the outbox as described in [../README.md](../README.md) |
| Instant Form leads are not in the CRM | That path does not exist | Pause the campaign. Export the leads from Ads Manager manually |

## Sources

- [Traffic objective](https://www.facebook.com/business/ads/ad-objectives/traffic) — confirmed 7 August 2026: optimises for link clicks, landing page views, or daily unique reach
- [Create a Facebook Page for your business](https://www.facebook.com/business/help/473994396650734)
- [How to choose a Special Ad Category](https://www.facebook.com/business/help/298000447747885)
- [Lead ads with forms](https://www.facebook.com/business/ads/ad-objectives/lead-generation/lead-ads-with-forms)

Meta's Help Centre pages load their content with JavaScript and could not be read
by an automated check, so exact button labels here come from current
practitioner documentation of the February 2026 unified campaign flow rather than
from a Meta page quote. The structure — campaign, ad set, ad; Traffic; Special Ad
Category; placement control — is stable. Confirm the wording in your account.
