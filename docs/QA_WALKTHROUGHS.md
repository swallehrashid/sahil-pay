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
```

Notes

- Tenants sign in with the OTP printed in `/tmp/sahilpay-api.log` (simulation mode).
- `lease-flow.mjs` expects `signed-page-1.jpg` / `signed-page-2.jpg` in `QA_SCRATCH`.
- `billing-flow.mjs` sets the Acme account's balance directly in the dev database to put it
  in a locked state, and uses the "Simulate: customer paid" control, which only exists in
  simulation mode.
- Each script prints PASS/FAIL per check and exits non-zero on any failure.
