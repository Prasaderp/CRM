# Go-live checklist

Everything that has to be settled before the CRM handles a real enquiry from a
real person, and before any money is spent on ads.

The current release runs locally with invented data. Working through this list is
what turns it into something a business can run.

Use it in order: decisions first, because the technical work depends on them.

## 1. Decisions the client makes

Nothing below can be inferred from the code. Get an answer for each one, in
writing, from the person who owns the business.

- [ ] **Legal entity.** The registered name, address, and public contact details
      that will appear in ads and on the property page.
- [ ] **Markets.** Which country and state the properties are in, and where ads
      will be shown. This drives every legal question that follows.
- [ ] **What is being offered.** Sale, rent, brokerage, or new development. The
      disclosure rules differ.
- [ ] **Who receives enquiries.** The exact mailboxes for `RECIPIENT_ALLOW_LIST`.
      Every accepted enquiry goes to every address in that list, so keep it to
      the people who should see customer details.
- [ ] **Who can pause a campaign.** One named person, reachable the same day,
      with access to the ad accounts.
- [ ] **How long data is kept.** How long enquiries stay in the CRM, and what
      happens to them afterwards.

## 2. Technical readiness

- [ ] Frontend and API deployed on one HTTPS domain the client controls, with a
      valid certificate. `/p/<slug>` must open publicly.
- [ ] PostgreSQL provisioned, with migrations applied and automated backups that
      have been restored at least once as a test.
- [ ] Authenticated SMTP configured. Sender domain has SPF, DKIM, and DMARC
      records, or notification emails will land in spam.
- [ ] The email worker runs under a supervisor that restarts it.
- [ ] `ENVIRONMENT=production`, `secure_cookies` on, and `trusted_origins` set.
      The application refuses to start without these outside local.
- [ ] Each property inserted as a database row with an active slug. Properties
      are never created from a link or a form field.
- [ ] `RECIPIENT_ALLOW_LIST` set to the approved mailboxes.
- [ ] Staff accounts created, one per person, with the right role.
- [ ] The form's privacy notice version matches the published notice. The test
      values currently in `frontend/src/features/lead-capture/LeadForm.tsx` must
      be replaced.
- [ ] Health checks monitored, with an alert when readiness fails or when jobs
      appear in the outbox `dead` state.

## 3. Privacy notice

- [ ] A privacy notice published at a public HTTPS address, saying who collects
      the data, why, who receives it, how long it is kept, and how to contact the
      client about it.
- [ ] The notice has a version identifier, and that identifier is what the form
      sends and the server records.
- [ ] The form separates "contact me about this property" from any optional
      marketing consent. Contact consent is required to submit; marketing is not.
- [ ] A working contact address for privacy questions and complaints, monitored
      by someone.

### India: the DPDP timeline

The Digital Personal Data Protection Act 2023 and its 2025 Rules commence in
stages:

| Date | What begins |
|---|---|
| 13 November 2025 | The Data Protection Board is constituted |
| 13 November 2026 | Consent manager registration and related Board powers |
| 13 May 2027 | Notice and consent duties, individual rights, breach reporting, and penalties |

So the main operating obligations are not yet enforceable in August 2026, but
they will be before most campaigns have run their course. Build the notice,
consent record, and deletion process now — the system already stores a consent
snapshot with each enquiry, which is the hard part.

Have a lawyer confirm this against the current gazette before launch rather than
relying on this table.

## 4. Property and advertising law

- [ ] **RERA.** Identify the authority for the state the property is in. Get the
      project registration and the agent registration, and confirm exactly how
      the state requires them to be displayed — several states require a QR code
      or the registration number in a specific position in the advertisement.
      Rules differ by state; do not copy another state's requirement.
- [ ] Every claim in the ad about price, availability, possession date, and
      approvals is current and can be evidenced.
- [ ] Images are the client's own or properly licensed, and show the actual
      property or clearly labelled representations.
- [ ] **Housing and discrimination rules.** Meta requires a Housing special ad
      category declaration in a growing number of markets, and X restricts
      housing ad targeting in some countries. Both restrict which audience
      controls you may use. Check what applies in your market and declare it.
- [ ] The platform's real-estate advertising policy has been read for the
      specific market, on or near the launch date.

## 5. Test before spending

Complete the link test in
[social-platform-setup/README.md](./social-platform-setup/README.md) for every
platform and property you intend to launch. Beyond that:

- [ ] Submit a test enquiry with the database stopped. The page must not report
      success.
- [ ] Submit one with the mail server stopped. The page must report success and
      the email must arrive once the mail server returns.
- [ ] Double-click submit. One enquiry, one reference.
- [ ] Confirm an expired staff session redirects to sign-in and shows no customer
      data.
- [ ] Read the API and worker logs. No names, email addresses, phone numbers,
      query strings, cookies, or tokens should appear.
- [ ] Delete the test enquiries.

## 6. The ad and the page must say the same thing

Check each pair before publishing:

- [ ] Same business name and same property.
- [ ] Same price, availability, and location, with the same qualifications.
- [ ] The ad's call to action describes what the page actually does — request
      information, not "book now" or "get approved".
- [ ] The confirmation message promises a reply, not an approval or a reservation.
- [ ] The form does not ask anything sensitive or anything that could be used to
      exclude people from housing.

## 7. Records to keep

Keep these where the client keeps business records, not in this repository, and
never store access tokens, passwords, payment details, or customer data in them:

- [ ] Who owns each account (Page, ad account, Instagram, X handle), and who has
      access at what level.
- [ ] Screenshots of the final ad preview and the destination for each launch.
- [ ] Property and agent registration documents.
- [ ] The published privacy notice and its version.
- [ ] The result of the pre-launch tests in section 5.
- [ ] Who approved the copy, images, budget, and targeting, and when.

Review these whenever the property, creative, market, or account access changes,
and at least every three months.

## 8. Sign-off

Before the first real campaign, three people should agree in writing:

| Role | Confirms |
|---|---|
| Business owner | Budget, property, offer, and who receives enquiries |
| Technical owner | Sections 2 and 5 are complete and were tested |
| Legal adviser | Sections 3 and 4 for this market and property |

Record the campaign start date, end date, and budget limit, and confirm the named
person can actually pause the campaign — test it once, on a live campaign, with a
small budget.

Software can enforce the decisions recorded here. It cannot decide whether an
advertisement is lawful. That judgement stays with the people signing off.
