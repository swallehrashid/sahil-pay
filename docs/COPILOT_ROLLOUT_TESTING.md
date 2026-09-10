# CO-PILOT — Implementation Order, Testing & Go-Live Checklist

> How to sequence `COPILOT_PLATFORM_SPEC.md` and `COPILOT_APP_SPEC.md`, and how YOU
> (Swalleh) verify each phase before moving on. The key property of this plan: **the
> entire backend is testable with `curl` before a single line of Kotlin exists**, because
> the device API is just JSON over HTTP.

---

## Phase 1 — Backend foundation (platform spec §2–§3)
Models + migration + parser engine + pipeline service + seeds.

**Verify:**
```bash
cd server && source venv/bin/activate
flask db upgrade                      # migration applies cleanly on your dev DB
python -m pytest tests/test_copilot_service.py -q   # full suite green (spec §11)
```
Also downgrade/upgrade once to prove the migration reverses.

## Phase 2 — Device API (platform spec §4)
`copilot_routes.py`: pair / heartbeat / ingest / app-latest, blueprint registered.

**Verify by playing "the app" with curl** (seeded landlord has `copilot_enabled=True`):
```bash
# 1. Landlord generates a code in the portal (or grab agent_code from the seed output)

# 2. Pair — save the device_token from the response
curl -s localhost:5000/api/copilot/pair -H 'Content-Type: application/json' -d '{
  "agent_code": "AB12CD34", "device_name": "Test cURL phone",
  "device_model": "curl/8", "app_version": "0.0.1"}'

# 3. Forward a fake M-Pesa SMS (matches the seeded MPESA template)
curl -s localhost:5000/api/copilot/ingest -H 'Content-Type: application/json' \
  -H 'X-Copilot-Token: <TOKEN>' -d '{"messages":[{
    "client_uuid":"11111111-1111-1111-1111-111111111111",
    "sender_id":"MPESA",
    "text":"SFR4XKPLM0 Confirmed. Ksh12,500.00 received from JANE WANJIKU 254712345678 on 7/7/26 at 10:34 AM",
    "received_at":"2026-07-07T10:34:00"}]}'
```
Walk this matrix with curl — each row is one request, check response + DB/portal:

| Case | Expect |
|---|---|
| Valid SMS, tenant phone matches, auto_allocate OFF | `parsed/matched`, Payment `pending`, landlord notification "awaiting allocation" |
| Same request again (same `client_uuid`) | `duplicate`, no second payment |
| Same text, new `client_uuid` | `duplicate` (dedupe_hash) |
| Valid SMS, unknown phone/account | `parsed/unmatched`, unmatched notification, no Payment |
| Gibberish text from sender `KCB` | `unparsed`, appears in admin unparsed queue |
| Landlord toggles auto-allocate ON, new valid SMS | Payment `confirmed`, allocations exist, invoice `amount_paid` moved |
| Bad token | 401 |
| Revoked device token | 401 |
| `copilot_enabled=False` | messages `rejected`, response says `copilot_enabled:false` |

## Phase 3 — Landlord portal (platform spec §5–§6)
Settings → Co-pilot tab, device table, activity feed, payments-page touches.

**Verify (browser or Playwright):** enable with consent modal → generate code → pair via curl → device appears with last-seen → ingest a payment → notification bell fires → pending payment confirm+allocate via ConfirmPaymentModal → revoke device → curl now gets 401. Check a team member without `settings/edit` cannot flip the toggles.

## Phase 4 — Admin portal (platform spec §7–§8)
Admin API + six pages.

**Verify:** overview tiles show phase-2 traffic → ingest log shows raw SMS on expand → open unparsed queue → "Create template" from the gibberish KCB message → placeholder editor + live test passes → save → "Retry all for KCB" → message becomes parsed and (if matched) creates the pending payment → device revoke + landlord `admin_locked` both stop ingestion immediately (curl confirms) → upload a dummy APK release → `GET /api/copilot/app/latest` returns it. Confirm every one of these actions landed in MasterAuditLogs.

## Phase 5 — Kotlin app (app spec, separate repo)
Build order inside the app: theme/scaffold → pairing → Room + receiver + queue → flush worker → screens → heartbeat/banners → self-update. Point debug builds at your dev server (`SAHIL_BASE_URL`).

**Verify on emulator first** — no SIM needed:
```bash
# Android Studio emulator: fake an incoming SMS from sender "MPESA"
adb emu sms send MPESA "SFR4XKPLM1 Confirmed. Ksh8,000.00 received from PETER OTIENO 254798765432 on 7/7/26 at 2:10 PM"
```
Then run the app-spec §12 "definition of done" list (7 items) on the emulator, then repeat items 1–5 on a **real phone** (ideally a Tecno/Infinix/Xiaomi — the aggressive-battery OEMs your clients actually own), including the overnight test: pair it, leave it unplugged overnight, text it in the morning, confirm the payment arrives without opening the app.

## Phase 6 — End-to-end dress rehearsal (production-like)
1. Deploy backend + portals to your staging/production host.
2. Build a **release** APK signed with the final keystore (back the keystore up NOW — app spec §8).
3. Upload via admin Releases; install on a clean phone from the public download link (the exact client experience: unknown-sources prompt included).
4. Full journey as a landlord: enable Co-pilot → generate code → pair → select real bank senders → have someone send an M-Pesa payment to your till/number → watch it land as pending → confirm+allocate → receipt/automation fires.
5. Full journey as admin: watch the same payment in the ingest log; check overview stats.
6. Send a real KCB/Equity alert (or paste its text as a template sample) — tune templates with the first real formats. **This is the "samples later" step you chose.**
7. Version bump → upload v1.0.1 → confirm the phone self-updates.

## Onboarding a real client (repeatable runbook)
1. Portal: client enables Settings → Co-pilot (consent) and picks allocation mode (default: review first).
2. Portal: generate agent code; client copies it.
3. Send the client the APK download link → install (guide through unknown-sources) → paste code → grant SMS + battery exemption → tick their banks.
4. You (admin): confirm the device shows in Co-pilot → Devices with a recent heartbeat.
5. Ask the client to make (or wait for) one small real payment; watch it in the ingest log; if the bank's format is new, build the template from the unparsed queue on the spot and retry.
6. Done — check the device's last-seen the next day to confirm overnight survival.

## Success criteria for v1
- ≥ 95 % of SMSs from configured senders end up `parsed` (rest visible in the unparsed queue, recoverable by template+retry — nothing silently lost).
- Zero duplicate Payments in any retry/replay scenario.
- A payment is visible in the landlord portal within 60 s of the SMS arriving (phone online).
- Every ingested message is traceable end-to-end: raw SMS → parse fields → tenant match → payment → allocation, all in the admin ingest log + audit trail.
- Admin can onboard a brand-new bank without touching code, in under 5 minutes, from an unparsed example.
