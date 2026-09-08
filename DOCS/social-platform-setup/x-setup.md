# X

Read [README.md](./README.md) first — it has the link format and the link test
that this guide assumes you have done.

**What works today:** an X post or a Website Traffic ad carries the property link,
the person lands on the client's website, and the enquiry reaches the CRM.

**What does not:** X has no native lead-form product connected to this CRM, and
the X Pixel is not installed.

## 1. X requires a paid subscription before you can advertise

This is the difference that catches people out. Facebook, Instagram, and TikTok
let you open an ad account for free. X does not: the account running ads must be
verified through a paid subscription first.

- A business advertises through the tier for organisations. In October 2025 X
  renamed and split that product — **Premium Business** (gold check) is the
  business tier; **Premium Organizations** (grey check) is for governments and
  multilateral bodies.
- An individual advertises through **X Premium**.

Check the current tiers and prices in the account before committing, and budget
for the subscription on top of ad spend.

X also enforces profile quality rules before ads will run:

- Profile photo and header image must be real images, not GIFs.
- The bio must contain a working URL that is live, not behind a login or
  paywall, and genuinely represents what you are advertising.
- The account and its posts must be public.

The bio URL rule is worth using deliberately: point it at the property page with
`utm_source=x&utm_medium=social&utm_content=x-bio`. It satisfies the requirement
and captures profile traffic at the same time.

## 2. Accounts

1. Prepare the client-owned handle: real business name, profile photo, header
   image, complete bio, verified email, confirmed phone number, and public
   posts. Post a few times before applying — a brand-new empty account is more
   likely to be rejected.
2. Subscribe to the appropriate verification tier and wait for it to be applied.
3. Open X Ads Manager and create the ads account. Set the country and currency
   correctly; these are not easily changed.
4. Add the payment method in the client's name, with a billing address matching
   the stated business location.
5. Give each person their own access at the level they need. Do not share the
   login.

## 3. Every X link goes through `t.co`

X rewrites all links in posts and ads to a `t.co` address. You cannot switch this
off, and you should not try to work around it.

It is harmless: `t.co` redirects to your full URL, so the parameters still reach
the property page. But it means one redirect hop is already spent. Do not add a
shortener or a redirect of your own on top of it — the link test in
[README.md](./README.md) exists mainly to prove the parameters survive this hop.

## 4. Publish a post

1. Sign in as the client's account.
2. Write the post and paste the complete property link. X shows a `t.co` link and
   usually a preview card — that is expected.
3. The post text must agree with the property page on price, availability,
   location, and who is selling, and must carry the registration details the page
   shows.
4. Attach your own or licensed images.
5. Post, then open it in a logged-out browser and click the link.

To schedule, use the scheduling control in the post composer and check the
scheduled queue afterwards.

## 5. Run a Website Traffic ad

X campaigns have three levels: campaign, ad group, and the posts promoted within
it.

### Campaign

1. In X Ads Manager, create a campaign and choose the **Website Traffic**
   objective. X's objectives are Reach, Video Views, Pre-roll Views, App
   Installs, Website Traffic, and Engagements.
2. Name it with the campaign key that is in your link.
3. Set the budget and either an end date or a named person responsible for
   stopping it.

### Ad group

1. Goal: **Link clicks**. Do not choose **Site Visits** — that goal needs the X
   Pixel with configured events, and Ads Manager will send you into Event Manager
   to set it up. No pixel is installed.
2. Bidding: autobid is the simplest starting point. Maximum bid and target cost
   are also available, and target cost only applies to the link-click goal.
3. Set the schedule, locations, and audience settings the market's housing rules
   allow.
4. Placements: keep it to the timeline for a first campaign.

### Creative

1. Promote a post that carries the property link — either an existing post you
   have already checked, or one written for the campaign.
2. If you use a website card or website button, put the complete property link in
   its URL field.
3. Preview the ad, click through, and confirm the `t.co` link resolves to the
   property page with all four `utm_` values intact. X may add `twclid`; the CRM
   handles it.
4. Submit.

## 6. After launch

Run the link test from the live ad preview on a real phone, including X's in-app
browser. Confirm the enquiry arrives with source `x` and the expected campaign
key, and that the email reached every recipient.

Watch for housing-related policy restrictions in your market. X restricts
targeting for housing, credit, and employment ads in some countries, and may
require approval before such ads run.

## 7. Problems

| What you see | Cause | Fix |
|---|---|---|
| Ads Manager will not let you create a campaign | The account is not verified | Subscribe to the correct tier and wait for it to apply |
| Ads rejected for account quality | GIF profile image, incomplete profile, or a gated bio URL | Fix the profile; the bio URL must load without a login |
| The link shows as `t.co` in the post | Normal — X rewrites every link | Test that it resolves correctly; do not try to prevent it |
| Parameters missing after the redirect | Something else is also redirecting, or the link was truncated | Rebuild the link and retest; remove any shortener |
| CRM source shows `unknown` | `utm_source` misspelled | It must be exactly `x`, lowercase, one character |
| Ads Manager asks for a pixel | You selected the Site Visits goal | Switch the ad group goal back to link clicks |

## 8. X Pixel and conversions

The X Pixel is not installed, by decision. It measures ad performance; it does
not deliver leads, and the CRM never depends on it. Installing it would mean a
privacy review, a consent mechanism, and code that fires only after the CRM has
durably saved an enquiry. Until then, the Website Traffic objective with the
link-click goal is the correct choice and needs nothing installed on the site.

## Sources

- [Create a website traffic campaign](https://business.x.com/en/help/campaign-setup/create-a-website-traffic-campaign)
- [Optimizing website traffic campaigns](https://business.x.com/en/help/campaign-editing-and-optimization/optimizing-website-traffic-campaigns)
- [About eligibility for X Ads](https://business.x.com/en/help/ads-policies/campaign-considerations/about-eligibility-for-x-ads)
- [URL requirements for advertising](https://business.x.com/en/help/ads-policies/campaign-considerations/url-requirements-for-advertising)
- [Housing, lending, and employment opportunities](https://business.x.com/en/help/ads-policies/campaign-considerations/housing-lending-and-employment-opportunities)
- [About X Premium Business](https://help.x.com/en/using-x/premium-business) and [Premium Organizations](https://help.x.com/en/using-x/premium-organizations) — the October 2025 split of Verified Organizations

X's help pages block automated readers, so the details above were confirmed from
current indexed summaries of those official pages rather than fetched directly.
Objective names, goals, bid types, and the verification requirement are
consistent across sources; confirm exact labels in Ads Manager.
