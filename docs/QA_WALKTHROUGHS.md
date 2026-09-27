# QA walkthroughs (Playwright)

Browser walkthroughs that drive the real UI against a local stack and save
screenshots. Run the API (`server/dev-restart.sh`) and Vite (`npm run dev`) first.

```bash
cd client
QA_SHOTS=/tmp/sahilpay-qa node scripts/qa/lease-flow.mjs        # leases: send → sign on paper / in portal → review → both download
QA_SHOTS=/tmp/sahilpay-qa node scripts/qa/billing-flow.mjs      # installments, lock/unlock, pending-until-confirmed, receipts
QA_SHOTS=/tmp/sahilpay-qa node scripts/qa/nav-responsive.mjs    # grouped nav on phone, tablet, laptop, desktop, TV
QA_SHOTS=/tmp/sahilpay-qa node scripts/qa/branding-tables.mjs   # contacts/colours on emails, receipts, reports; ruled tables
QA_SHOTS=/tmp/sahilpay-qa node scripts/qa/copilot-download.mjs  # /copilot on a throttled phone; APK checksum

# September 2026 eight-item release — need the scale estate: server/seed_scale.py --wipe --months 4
QA_SHOTS=/tmp/sahilpay-qa node scripts/qa/dropdowns-scale.mjs     # 1: every dropdown lists all 100 / 1,000 and searches them
QA_SHOTS=/tmp/sahilpay-qa node scripts/qa/cascade-delete.mjs      # 3: property → units → tenants; redeploy clean-up of headless tenants
QA_SHOTS=/tmp/sahilpay-qa node scripts/qa/sms-phones-audit.mjs    # 4, 5, 7: SMS charged to the account; 07/254 sign-in; audit in Nairobi time
QA_SHOTS=/tmp/sahilpay-qa node scripts/qa/team-e2e.mjs            # 6, 8: full-access / caretaker / viewer; 4 monthly cycles at 1,000 tenants
QA_SHOTS=/tmp/sahilpay-qa node scripts/qa/team-tutorials.mjs      # 6: a team member's tour highlights the right menu item
QA_SHOTS=/tmp/sahilpay-qa node scripts/qa/backup-and-delete.mjs   # 2: DESTRUCTIVE — empties the scale account; run last
```

Notes

- Tenants sign in with the OTP printed in `/tmp/sahilpay-api.log` (simulation mode).
- The login limit is 5/min, 30/hour per IP. Run `server/dev-reset-ratelimit.sh` between passes.
- `team-e2e.mjs` invoices the four months after the last month the account was invoiced for,
  so it can be run repeatedly against the same estate.
- `lease-flow.mjs` expects `signed-page-1.jpg` / `signed-page-2.jpg` in `QA_SCRATCH`.
- `billing-flow.mjs` sets the Acme account's balance directly in the dev database to put it
  in a locked state, and uses the "Simulate: customer paid" control, which only exists in
  simulation mode.
- Each script prints PASS/FAIL per check and exits non-zero on any failure.
