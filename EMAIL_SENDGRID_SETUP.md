# SahilPay — Email / SendGrid Setup Guide

This document explains the email system that was built and gives you the exact
step-by-step to connect SendGrid with **innit819@gmail.com** so SahilPay
can send OTPs, verification links, password resets and team invites.

---

## 1. What was built

| Capability | How it works | Where |
|------------|--------------|-------|
| **Tenant OTP by SMS *or* email** | The tenant types their **phone** → OTP via SMS, or their **email** → OTP via email. The channel is chosen by what they enter. | `routes/otp_routes.py`, `send_otp_email` |
| **Landlord email verification** | On signup a verification email is sent. Clicking the link sets the account `is_verified = true`. Optionally required before login. | `auth_routes.py::register / verify_email`, `send_verification_email` |
| **Team member onboarding** | Creating a team member now generates a **temporary password** and emails them their **email + username + temp password** plus how to log in. They’re **forced to change the password on first login**. | `team_routes.py::create_team_member`, `send_team_credentials_email`, `ChangePassword.jsx` |
| **Password reset (all roles)** | “Forgot password” emails a reset link that works for landlords, team members and tenants. | `auth_routes.py::forgot_password / reset_password`, `send_password_reset_email` |
| **Branded emails** | Every email uses one SahilPay-themed HTML template (deep-indigo gradient card, rose buttons, the SahilPay wordmark). | `services/email_templates.py` |
| **Resend verification** | `POST /api/auth/resend-verification` re-issues the link for an unverified account. | `auth_routes.py` |

**Key behaviour:** if `SENDGRID_API_KEY` is **not** set, emails are **logged to the
server console** instead of sent — so nothing breaks while you’re still setting up.
The moment you add a valid key and restart, real emails go out.

---

## 2. Connect SendGrid — step by step

### Step 1 — Create / log in to a SendGrid account
1. Go to **https://sendgrid.com** and sign up (the free plan sends ~100 emails/day — plenty for testing).
2. Verify your own SendGrid login email and complete the short onboarding.

### Step 2 — Verify `innit819@gmail.com` as a Sender
SendGrid will not send from an address it hasn’t verified.
1. In the SendGrid dashboard go to **Settings → Sender Authentication**.
2. Under **Single Sender Verification**, click **Create New Sender**.
3. Fill the form:
   - **From Name:** `SahilPay`
   - **From Email Address:** `innit819@gmail.com`
   - **Reply To:** `innit819@gmail.com`
   - Company name / address: anything reasonable.
4. Click **Create**. SendGrid emails a confirmation link to **innit819@gmail.com**.
5. Open that inbox, click the confirmation link → the sender shows **Verified**.

> This is the address SahilPay sends **from**. To **receive** test OTP/verification
> emails at this same Gmail, just use `innit819@gmail.com` as a tenant’s email
> or a landlord’s signup email (see §3).

### Step 3 — Create an API Key
1. Go to **Settings → API Keys → Create API Key**.
2. **Name:** `sahilpay-server`.
3. **Permissions:** choose **Restricted Access** and enable **Mail Send → Full Access**
   (or just pick **Full Access** for simplicity).
4. Click **Create & View**. **Copy the key now** — it starts with `SG.` and is shown only once.

### Step 4 — Put the key in SahilPay’s `.env`
1. Open **`server/.env`** (it was created for you; values there are git-ignored).
2. Set:
   ```env
   SENDGRID_API_KEY=SG.your-real-key-here
   MAIL_DEFAULT_SENDER=innit819@gmail.com
   MAIL_DEFAULT_SENDER_NAME=SahilPay
   FRONTEND_URL=http://localhost:5173
   ```
   (`MAIL_DEFAULT_SENDER` **must** equal the address you verified in Step 2.)

### Step 5 — Restart the Flask server
Environment variables load at startup, so restart the backend:
```bash
# stop the running server (Ctrl-C in its terminal), then:
cd server
source venv/bin/activate
python app.py
```

### Step 6 — Send a real test email
Trigger any flow and watch the inbox of **innit819@gmail.com**:

- **Password reset (quickest test):**
  ```bash
  curl -X POST http://localhost:5000/api/auth/forgot-password \
    -H "Content-Type: application/json" \
    -d '{"email":"innit819@gmail.com"}'
  ```
  (Use an email that belongs to a real account; for a brand-new test, register a
  landlord with that email first — see §3.)

- **Verify it sent:** the server log should now print
  `Email sent to innit819@gmail.com via SendGrid: ...`
  instead of the `EMAIL [stub — SendGrid not configured]` line.
  In SendGrid, **Activity Feed** (Email Activity) also shows each delivery.

> First emails from a new Gmail single-sender can land in **Spam** — check there and
> mark “Not spam”. For production deliverability, later set up **Domain Authentication**
> on a domain you own instead of a gmail.com sender.

---

## 3. How to test each flow end-to-end

> Use **innit819@gmail.com** wherever an email is asked for, so the email
> lands in your inbox.

1. **Landlord verification**
   - Register at `http://localhost:5173/register` using `innit819@gmail.com`.
   - Open the **“Confirm your email”** email → click **Verify my email** → account becomes verified.
   - To *require* verification before login, set `ENFORCE_EMAIL_VERIFICATION=true` in `.env` and restart. (Default is off in development so you’re never locked out.)

2. **Tenant OTP (email or SMS)**
   - As a landlord, create a tenant whose **email** is `innit819@gmail.com`.
   - Go to `http://localhost:5173/tenant/login`, enter that **email** → you receive the **6-digit code by email**.
   - Enter the tenant’s **phone** instead → the code goes by **SMS** (needs the Africa’s Talking SMS key; until then it’s logged).

3. **Team member invite + forced password change**
   - Landlord → **Settings → Team → Add team member** (use `innit819@gmail.com`).
   - You receive **“Your team account is ready”** with email, username and a **temporary password**.
   - Log in with those at `/login` → you’re forced onto **Set your password** → set a new one → you land in the team portal.

4. **Password reset (any role)**
   - On `/login` click **Forgot password**, enter `innit819@gmail.com`.
   - Open **“Reset your password”** → click the button → set a new password.

---

## 4. Files changed / added (for reference)

```
server/services/email_templates.py        NEW — branded HTML email builder (SahilPay theme)
server/services/email_service.py          all emails rewritten to branded templates; + send_team_credentials_email
server/routes/team_routes.py              team create now issues a temp password + credentials email
server/routes/auth_routes.py              login verification gate; must_change_password in login; /resend-verification; reset clears flag
server/routes/settings_routes.py          password change clears must_change_password
server/models.py                          users.must_change_password column
server/migrations/versions/a1b2c3d4e5f6_add_must_change_password.py   migration (already applied)
server/config.py                          ENFORCE_EMAIL_VERIFICATION flag
server/.env / server/.env.example         SendGrid + mail config keys
client/src/features/auth/ChangePassword.jsx   NEW — forced password-change screen
client/src/features/auth/Login.jsx        redirects to change-password when required
client/src/components/ProtectedRoutes.jsx guards every route until temp password is changed
client/src/routes/AppRoutes.jsx           /change-password route
client/src/config/routePaths.js           changePassword path
```

---

## 5. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Log shows `EMAIL [stub — SendGrid not configured]` | `SENDGRID_API_KEY` is empty or the server wasn’t restarted after editing `.env`. |
| `_send_email failed ... 401` | Bad/expired API key, or the key lacks **Mail Send** permission. |
| `_send_email failed ... 403` Forbidden | The **From** address (`MAIL_DEFAULT_SENDER`) isn’t a **verified sender** in SendGrid. Redo Step 2. |
| Email sent but not in inbox | Check **Spam**; check SendGrid **Email Activity** for “Delivered/Blocked/Dropped”. |
| Want emails required before login | Set `ENFORCE_EMAIL_VERIFICATION=true` and restart. |
