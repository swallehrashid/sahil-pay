# SMS Balance Source of Truth + Google Sign-In

Two changes shipped together (branch `backend-set-up`).

---

## 1. SMS credit balance — now a derived source of truth

### What went wrong in production

A landlord bought **1,000 credits for KES 500** (their negotiated rate of 0.50 /
SMS) but their balance read **2,000**. Root cause: `landlords.sms_balance` was a
free-running counter (+credits on purchase, −credits on send) with no memory of
how it got where it was. One M-Pesa payment reached the server **twice** — the
STK push callback finalised the pending purchase (+1,000), and Safaricom's C2B
confirmation of the *same money* created a second transaction and credited again
(+1,000). The per-transaction idempotency guard could not catch it because there
were two transaction rows.

### The fix

**Source of truth** (`services/sms_credit_ledger.py`):

```
balance = confirmed-purchase credits   (one grant per M-Pesa receipt)
        + genuine admin manual credits (excluding reconciliation rows)
        − credits used on charged sends (communication_logs.sms_credits)
```

- **Deduped by receipt** — the two confirmations of one payment collapse to a
  single grant.
- **Only confirmed, non-reversed purchases count.** Failed, pending-unconfirmed
  and reversed payments contribute nothing.
- **Usage is the credits actually charged**, read from the new
  `communication_logs.sms_credits` column (not `sms_segments`, which is the raw
  GSM segment count — a different unit).

**Source-side prevention** (`services/billing_service.finalize_sms_purchase`):
crediting is now idempotent on the M-Pesa receipt, so a second confirmation of
the same payment verifies but adds nothing. One payment credits exactly once.

**Self-healing on deploy.** Two migrations run automatically via `flask db
upgrade` (already part of `deploy/update.sh`):

| Migration | Does |
|---|---|
| `d1f2a3b4c5d6` | Adds `communication_logs.sms_credits`; backfills historical usage from each message's content using the live word→credit tiers (only for charged sends). |
| `d2f3a4b5c6d7` | Rebuilds **every** non-demo landlord's `sms_balance` from the source of truth. Each corrected balance is written to the `sms_landlord_credits` ledger with a `SYS-RECON:` reason so the change is visible and auditable. Clean accounts (no duplicate, nothing reversed) compute back to the exact balance they already had and are left untouched. |

So once you redeploy, the affected client's balance drops from 2,000 back to the
1,000 they actually paid for, and their credit history shows the correction.

### Admin tools (`/api/admin/sms/...`)

- `GET  /landlords/<id>/balance-truth` — preview the derived balance and its
  components next to the current balance (read-only).
- `POST /landlords/<id>/resync` — rebuild one landlord's balance on demand
  (same computation as the migration). Idempotent.

### Tests

`tests/test_sms_balance_source_of_truth.py` — includes the end-to-end STK + C2B
double-confirmation regression. `tests/test_google_auth.py` covers sign-in.

---

## 2. "Continue with Google" for landlords & affiliates

One button that both **signs up** and **logs in**. Tenants are untouched (OTP
only). Decisions implemented:

- **Create then ask essentials** — Google verifies the email and the account is
  created instantly; a one-step modal then collects the company name + account
  type (landlord) or payout phone (affiliate). "Skip for now" is allowed.
- **Auto-link by verified email** — a Google sign-in whose email already belongs
  to a password account signs into that same account and attaches Google as an
  extra method; nothing is replaced.
- **2FA still enforced** — an account with 2FA on still completes the second
  factor after Google.
- Google accounts are marked email-verified (no verification email) and may have
  **no password** until the holder sets one; affiliates are created **pending
  admin approval** exactly like the form signup.

Backend: `POST /api/auth/google`, `POST /api/auth/complete-profile`
(`routes/auth_routes.py`); token verification in `services/google_auth.py` (JWKS
via PyJWT — no new dependency). Frontend: `GoogleAuthFlow` + `GoogleSignInButton`
on the login, landlord-register and affiliate-signup pages.

### Configuration required before it works

The feature is **off** until a Google OAuth client ID is set. Blank = buttons
hidden, backend refuses Google logins with a clear message. The client ID is
**not a secret** (it ships in the frontend bundle).

**Backend** (`server/.env`):
```
GOOGLE_CLIENT_ID=<your-web-client-id>.apps.googleusercontent.com
```

**Frontend** (`client/.env` / build env — same value):
```
VITE_GOOGLE_CLIENT_ID=<your-web-client-id>.apps.googleusercontent.com
```

### Creating the Google OAuth client (one-time)

1. Go to **Google Cloud Console → APIs & Services → Credentials**.
2. **Create Credentials → OAuth client ID → Web application**.
3. Under **Authorized JavaScript origins**, add every origin the app is served
   from:
   - `https://sahilpay.co.ke` (and any other production domain)
   - `http://localhost:5173` (local dev)
4. Leave **Authorized redirect URIs** empty — Google Identity Services uses the
   origins above, not a redirect.
5. Copy the generated **Client ID** into both env vars above and redeploy.
6. On the **OAuth consent screen**, publish the app (or add testers) so people
   outside your org can sign in.
