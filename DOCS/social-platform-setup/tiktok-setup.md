# TikTok

Read [README.md](./README.md) first — it has the link format and the link test
that this guide assumes you have done.

## 1. TikTok cannot be used from India

The Government of India blocked TikTok in June 2020 and the block is still in
force. In August 2025 the government publicly denied reports that it had been
lifted, and no order lifting it has been issued since.

For a client advertising in India this means:

- No TikTok account, TikTok Ads Manager account, or TikTok Business Centre.
- No ad spend, and no TikTok traffic to the property page.
- Using a VPN or a foreign entity to reach TikTok is a circumvention of the
  block, not a workaround. Do not do it, and do not build a process that assumes
  someone will.

This was confirmed while writing this guide: TikTok's own domains refuse
connections from an Indian network, including its advertiser help centre and its
developer documentation.

**If the client only advertises in India, stop here.** The rest of this guide
applies to a different market and should not be acted on.

The CRM already accepts TikTok's `ttclid` click parameter and can classify
`utm_source=tiktok`. That support is unused and costs nothing to keep, so no code
change is needed if TikTok ever becomes available.

## 2. If you advertise from a market where TikTok is available

Confirm two things before spending any time on setup:

1. TikTok advertising is legally available in the advertiser's country **and** in
   the country you want to show ads in.
2. TikTok accepts real-estate advertising in that market. Some markets require
   licence or registration details before a housing ad is approved.

Both are answered in TikTok Ads Manager for that specific account, not from
documentation. If either is unclear, do not proceed.

## 3. Accounts

1. Create the TikTok account the ads will be published from, and complete the
   profile — name, photo, bio, and website.
2. Create a TikTok Business Centre owned by the client's business.
3. Create the advertiser (ad) account inside the Business Centre, choosing the
   correct country, currency, and time zone. **These cannot be changed later** —
   an error here means starting over with a new account.
4. Complete business verification. TikTok asks for registration documents, and
   unverified accounts hit limits.
5. Link the TikTok account as an identity so ads can run under it.
6. Add each person with their own login and the least access they need.
7. Add the payment method.

## 4. Organic posts

TikTok captions do not produce a clickable link for most accounts. A URL in a
caption is text. Some accounts have a website field on the profile; where that
exists, put the property link there, exactly as built in
[README.md](./README.md), with `utm_source=tiktok`.

Treat organic TikTok as awareness. The reliable path from TikTok to the CRM is a
paid ad with a destination URL.

## 5. Run a Traffic ad

TikTok Ads Manager has three levels: campaign (objective and budget), ad group
(audience, placement, schedule, bidding), and ad (creative and destination URL).

If offered a choice between **Simplified Mode** and **Custom Mode**, choose
Custom Mode. Simplified Mode hides the placement and destination controls this
setup depends on.

### Campaign

1. Objective: **Traffic**. It optimises for clicks through to a destination URL
   and needs no pixel.
2. Name it with the campaign key that is in your link.
3. Set the budget and either an end date or a named person responsible for
   stopping it.

### Ad group

1. Placement: select TikTok only. TikTok's other placements have different
   audiences and rules.
2. Set the locations, schedule, and any audience settings the market's housing
   rules allow.
3. Leave off any setting that requires the TikTok Pixel, including anything
   optimising for on-site actions. No pixel is installed.
4. Optimisation goal: clicks.

### Ad

1. Upload the video or images. Vertical, full-screen, and captioned.
2. Write the ad text so it agrees with the property page on price, availability,
   and location.
3. Call to action: something factual such as **Learn more**.
4. **Destination URL:** paste the complete link with all parameters.
5. If TikTok offers to append its own URL parameters, leave that empty. Your link
   already has them.
6. Preview the ad, click through, and confirm the property page loads with all
   four `utm_` values intact. TikTok may add `ttclid`; the CRM handles it.
7. Submit for review.

## 6. After launch

Run the link test from the live ad preview on a real phone, including TikTok's
in-app browser. Confirm the enquiry arrives with source `tiktok` and the expected
campaign key, and that the email reached every recipient.

## 7. Problems

| What you see | Cause | Fix |
|---|---|---|
| TikTok Ads Manager will not open or the account cannot be created | The market is blocked or unsupported | Do not attempt to bypass it |
| Ad rejected | Real-estate or housing policy in that market | Read the rejection reason; supply licence details if requested |
| CRM source shows `unknown` | `utm_source` misspelled | It must be exactly `tiktok`, lowercase |
| Clicks reported but no enquiries | The destination is broken in the in-app browser, or the link lost its parameters | Retest from the live ad on a phone |
| Instant Form leads are not in the CRM | That path does not exist | Pause the campaign; download the leads from Ads Manager |

## 8. Instant Forms

TikTok Instant Forms keep leads inside TikTok. Nothing has been built to collect
them. TikTok also holds lead data in Ads Manager for a limited period only, so a
form left running without an integration will eventually lose leads that were
never downloaded. Confirm the current retention window in your account before
relying on manual export. See [native-lead-forms.md](../native-lead-forms.md).

## Sources and verification limits

TikTok's advertiser help centre (`ads.tiktok.com`) and developer portal
(`business-api.tiktok.com`, `developers.tiktok.com`) were unreachable from the
network used to write this guide, which is consistent with the Indian block.
The steps above therefore come from current secondary documentation of TikTok Ads
Manager and were not confirmed against a TikTok page.

**Treat every navigation step in sections 3 to 5 as unverified** and check it in
the account before use. Sections 1 and 2 — the India block and the market gate —
are the parts that matter for this client, and those are confirmed:

- [Government of India press release, 29 June 2020](https://www.pib.gov.in/PressReleasePage.aspx?PRID=1635206) — the original blocking order listing TikTok
- [No order issued to lift the ban on TikTok in India](https://www.newsonair.gov.in/no-order-issued-to-lift-ban-on-tiktok-in-india-govt) — government statement, August 2025
