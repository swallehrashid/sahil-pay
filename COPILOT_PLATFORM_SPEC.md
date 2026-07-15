# CO-PILOT PLATFORM SPEC — Backend + Landlord Portal + Admin Portal

> **Audience:** implementation agent (Sonnet) working in this repo.
> **Companion docs:** `COPILOT_APP_SPEC.md` (the Kotlin app), `COPILOT_ROLLOUT_TESTING.md` (build order + testing).
>
> **What Co-pilot is:** a sideloaded Android app installed on the landlord's phone. It
> listens for payment-confirmation SMSs from senders the landlord selects (MPESA, KCB,
> Equity Bank, …) and forwards the **raw SMS text** to the Sahil backend. The backend
> parses it (admin-managed templates), matches it to a tenant, and records a Payment —
> auto-allocated or pending-allocation depending on the landlord's setting.

---

## 0. Decisions already made (do not re-litigate)

| Decision | Choice |
|---|---|
| Device auth | Landlord pastes short **agent code** into the app ONCE → app exchanges it at `/pair` for a long-lived **device token**. Every subsequent call authenticates with the device token. Multiple devices per landlord allowed. Per-device revocation. |
| Parsing | **Server-side.** App forwards raw SMS + sender ID + received-at. Parser templates live in the DB, **admin-managed** — admin adds a sender (e.g. `KCB`) + an expected-message pattern with placeholders; no code change per new bank. |
| Tenant matching | `{account}` from SMS → exact `Tenant.account_number` → fallback sender `{phone}` → exact `Tenant.phone` → else **unmatched queue** + landlord notification. Sender name is a display hint only, never used for auto-match. |
| Manual-allocation landlords | Payment created with `status='pending'`, attributed to the matched tenant, **no balances touched** (existing rule: pending payments are not allocated). Landlord gets a "payment awaiting allocation" notification and confirms+allocates via the existing ConfirmPaymentModal flow. |
| Auto-allocate landlords | Payment created `status='confirmed'` and run through `allocation_service.apply_allocations` (auto mode) in the same transaction. |
| Auto/manual toggle + consent | Lives in **landlord portal Settings → Co-pilot** (server-side, audited). Enabling Co-pilot is the consent step. The app never decides ledger behaviour. |
| App updates | Backend hosts APK releases + a version endpoint; app self-checks. Admin uploads new APKs from the admin portal. |

---

## 1. What exists today (reuse, don't duplicate)

| Piece | Where | State |
|---|---|---|
| `PaymentSource.co_pilot` | `server/models.py:212` | ✅ use as-is |
| `Landlord.agent_code` (unique, nullable) | `server/models.py:660` | ✅ use as-is |
| `POST /api/settings/account/agent-code` (generate/regenerate) | `server/routes/settings_routes.py:561` | ✅ keep; add note in response that regenerating does **not** revoke already-paired devices |
| Agent-code card UI | `client/src/features/landlord/settings/AccountSettings.jsx` | ♻️ move into the new Co-pilot settings section (§6.1) |
| `POST /api/mpesa/copilot/ingest` | `server/routes/mpesa_routes.py:386` | ❌ **DELETE.** It requires a browser JWT (a phone app has none), ignores the `agent_code` it accepts, parses only one Safaricom format, matches only by phone, and its `auto_confirm` path bumps `tenant.balance` directly, bypassing `allocation_service` (ledger corruption under the category system). Replaced wholesale by §4. |
| `_parse_mpesa_sms` + `_MPESA_SMS_PATTERN` | `server/routes/mpesa_routes.py:91-112` | ❌ delete — superseded by DB templates (§3). Seed its pattern as the default `MPESA` template. |
| `MpesaTransaction` model + landlord match/list/status-check endpoints | `server/models.py:1547`, `mpesa_routes.py` | ✅ reuse as the transaction record for every ingested SMS (bank ones too — the name is historical; do NOT rename the table). `POST /transactions/<id>/match` is the existing manual-match tool — fix it per §4.6. |
| Allocation engine | `server/services/allocation_service.py` (`auto_allocate`, `normalize_manual_allocations`, `apply_allocations`) | ✅ the ONLY writer of allocations/ledgers. Copy the usage pattern from `payment_routes.py:200-217`. |
| Pending-payment confirm flow | `payment_routes.py` confirm endpoint + `client/.../payments/ConfirmPaymentModal.jsx` | ✅ reuse for manual-mode Co-pilot payments |
| Notifications | `services/notification_service.py::notify` (flush-not-commit contract) | ✅ extend template registry |
| Audit | `services/audit_service.py::record_audit` | ✅ use everywhere |
| Admin portal scaffolding | `client/src/features/admin/*`, `admin_routes.py` etc. | ✅ follow existing patterns (`adminApiSlice`, sidebar, drill-downs) |

---

## 2. New data model (in `server/models.py`, one Alembic migration)

### 2.1 Enums

```python
class CopilotDeviceStatus(str, enum.Enum):
    active  = "active"
    revoked = "revoked"

class CopilotParseStatus(str, enum.Enum):
    parsed    = "parsed"      # a template matched and extracted fields
    unparsed  = "unparsed"    # no active template matched → admin queue
    duplicate = "duplicate"   # dedupe hit; stored for traceability, no side effects
    rejected  = "rejected"    # e.g. landlord disabled, malformed payload

class CopilotMatchStatus(str, enum.Enum):
    matched   = "matched"     # tenant resolved (by account or phone)
    unmatched = "unmatched"   # parsed fine but no tenant hit → landlord queue
    n_a       = "n_a"         # not applicable (unparsed/duplicate/rejected)
```

Extend existing enums:
- `AuditEntityType`: add `copilot = "copilot"`.
- `NotificationCategory`: add `copilot_payment_pending`, `copilot_payment_unmatched`, `copilot_device_paired`. Register matching templates in `notification_service.py` TEMPLATES, e.g. `copilot_payment_pending` → title `"Payment awaiting allocation"`, body `"Co-pilot received KES {amount} from {sender_name} for {tenant_name}. Confirm and allocate it."`, link `/landlord/payments?status=pending`.

### 2.2 `CopilotDevice` — one row per paired phone

```python
class CopilotDevice(TimestampMixin, Base):
    __tablename__ = "copilot_devices"
    id                = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id       = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    device_name       = Column(String(100), nullable=False)          # landlord-chosen, e.g. "John's Samsung"
    device_model      = Column(String(100), nullable=True)           # reported by app (Build.MODEL)
    app_version       = Column(String(20),  nullable=True)           # reported by app, updated on heartbeat
    token_hash        = Column(String(64),  nullable=False, unique=True, index=True)  # sha256 of device token
    status            = Column(String(10),  default="active", nullable=False)          # CopilotDeviceStatus
    sender_ids        = Column(Text, nullable=True)                  # JSON array of configured senders, updated on heartbeat
    last_seen_at      = Column(DateTime, nullable=True)              # any authenticated call updates this
    revoked_at        = Column(DateTime, nullable=True)
    revoked_by        = Column(String(20), nullable=True)            # 'landlord' | 'admin'
    landlord = relationship("Landlord", backref="copilot_devices")
```

**Token scheme:** on pairing generate `secrets.token_urlsafe(32)`; return the raw token ONCE; store only `hashlib.sha256(raw.encode()).hexdigest()`. Lookup on each request is `filter_by(token_hash=sha256(presented))` — indexed, constant-time enough. Never log or re-display the raw token.

### 2.3 `CopilotMessage` — the ingest log (every SMS the platform ever received)

This is the audit backbone the admin asked for. One row per forwarded SMS, whatever the outcome.

```python
class CopilotMessage(CreatedAtMixin, Base):
    __tablename__ = "copilot_messages"
    id               = Column(Integer, primary_key=True, autoincrement=True)
    landlord_id      = Column(Integer, ForeignKey("landlords.id"), nullable=False, index=True)
    device_id        = Column(Integer, ForeignKey("copilot_devices.id"), nullable=False, index=True)
    client_uuid      = Column(String(40), nullable=False)            # generated by the app per SMS; idempotency key
    sender_id        = Column(String(30), nullable=False, index=True)  # SMS sender, e.g. "MPESA", "KCB"
    raw_text         = Column(Text, nullable=False)
    sms_received_at  = Column(DateTime, nullable=True)               # as reported by the phone (may be skewed)
    dedupe_hash      = Column(String(64), nullable=False, index=True)  # sha256(landlord_id|sender_id|raw_text)
    parse_status     = Column(String(12), nullable=False)            # CopilotParseStatus
    match_status     = Column(String(12), nullable=False, default="n_a")  # CopilotMatchStatus
    template_id      = Column(Integer, ForeignKey("sms_parser_templates.id"), nullable=True)
    parsed_ref       = Column(String(40),  nullable=True, index=True)
    parsed_amount    = Column(Numeric(12, 2), nullable=True)
    parsed_name      = Column(String(120), nullable=True)
    parsed_account   = Column(String(50),  nullable=True)
    parsed_phone     = Column(String(20),  nullable=True)
    error_reason     = Column(String(255), nullable=True)            # why unparsed/rejected/duplicate
    tenant_id        = Column(Integer, ForeignKey("tenants.id"),   nullable=True, index=True)
    payment_id       = Column(Integer, ForeignKey("payments.id"),  nullable=True, index=True)
    mpesa_transaction_id = Column(Integer, ForeignKey("mpesa_transactions.id"), nullable=True)
    __table_args__ = (
        UniqueConstraint("device_id", "client_uuid", name="uq_copilot_messages_device_uuid"),
    )
```

### 2.4 `SmsParserTemplate` — admin-managed, the "no backend change per bank" registry

```python
class SmsParserTemplate(TimestampMixin, Base):
    __tablename__ = "sms_parser_templates"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    name          = Column(String(100), nullable=False)              # "KCB credit alert"
    sender_id     = Column(String(30),  nullable=False, index=True)  # matched case-insensitively vs SMS sender
    template_text = Column(Text, nullable=False)                     # placeholder pattern (§3.1)
    sample_text   = Column(Text, nullable=True)                      # the example SMS admin pasted; used by the test console
    is_active     = Column(Boolean, default=True, nullable=False)
    priority      = Column(Integer, default=100, nullable=False)     # lower = tried first within a sender
    created_by    = Column(Integer, ForeignKey("system_admins.id"), nullable=True)
```

Global scope (no `landlord_id`) — all landlords share the registry; a KCB alert looks the same for everyone.

### 2.5 `CopilotAppRelease` — APK hosting for the in-app update check

```python
class CopilotAppRelease(CreatedAtMixin, Base):
    __tablename__ = "copilot_app_releases"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    version_name  = Column(String(20), nullable=False)   # "1.2.0"
    version_code  = Column(Integer, nullable=False, unique=True)  # monotonically increasing
    apk_path      = Column(String(255), nullable=False)  # under server/uploads/copilot/
    release_notes = Column(Text, nullable=True)
    is_latest     = Column(Boolean, default=False, nullable=False)  # exactly one True; setting it clears others
    min_supported_version_code = Column(Integer, nullable=True)    # below this, app must update before forwarding
    uploaded_by   = Column(Integer, ForeignKey("system_admins.id"), nullable=True)
```

### 2.6 `LandlordSettings` additions (existing table, `models.py:2614`)

```python
copilot_enabled       = Column(Boolean, default=False, nullable=False)  # consent + master switch
copilot_auto_allocate = Column(Boolean, default=False, nullable=False)  # False → pending-allocation flow
copilot_consented_at  = Column(DateTime, nullable=True)                 # set the first time enabled flips True
copilot_admin_locked  = Column(Boolean, default=False, nullable=False)  # admin kill switch; landlord cannot re-enable while True
```

Add all of these to `to_dict()`.

---

## 3. Parser template engine (`server/services/copilot_service.py` — new file)

### 3.1 Placeholder syntax (what the admin types)

The admin pastes the bank's message and swaps the variable parts for placeholders:

```
{ref} Confirmed. Ksh{amount} received from {name} {phone} on {*} at {*}
KCB: {name} has paid Ksh {amount} to your account {account} Ref {ref} on {*}
```

| Placeholder | Compiles to (named group) | Post-processing |
|---|---|---|
| `{amount}` | `(?P<amount>[\d,]+(?:\.\d{1,2})?)` | strip commas → `Decimal`; **reject ≤ 0** |
| `{ref}` | `(?P<ref>[A-Z0-9]{6,20})` | uppercase |
| `{name}` | `(?P<name>.+?)` (lazy) | strip |
| `{account}` | `(?P<account>[A-Za-z0-9\-/#\.]{1,50})` | strip |
| `{phone}` | `(?P<phone>(?:\+?254|0)[17]\d{8})` | normalise to `2547…`/`2541…` |
| `{date}` / `{time}` | permissive date/time group, value discarded in v1 | — |
| `{*}` | `.*?` non-capturing wildcard | — |

Compiler rules (`compile_template(template_text) -> re.Pattern`):
1. `re.escape` all literal text between placeholders, then splice in the group regexes; flags `re.IGNORECASE | re.DOTALL`; match with `.search()` (leading operator text tolerated).
2. Collapse literal whitespace runs to `\s+` (banks vary spacing).
3. **Validate on save:** must contain `{amount}`; must not contain two adjacent placeholders with no literal separator (ambiguous, rejects with a clear error); unknown `{foo}` placeholder → 400. Compiled patterns contain no nested quantifiers, so catastrophic backtracking is structurally impossible — still wrap `.search()` in a 100 ms guard for safety (thread-based timeout or `regex` module if already available; otherwise document the guard as best-effort).
4. Cache compiled patterns in-process keyed by `(template_id, updated_at)`.

`parse_sms(sender_id, raw_text) -> (template, fields) | (None, None)`: fetch active templates for the sender (case-insensitive exact match on `sender_id`), ordered by `priority, id`, return the first that matches.

### 3.2 Seed templates (migration data or `seed.py`)

Seed known public formats so day one works — admin tunes with real samples later.
Two adjacent free-text placeholders (`{name}`/`{date}`/`{time}`/`{*}`) with no literal
separator are rejected at compile time (§3.1 rule 3) — every seed below keeps a literal
word/punctuation between any two loose placeholders, verified against its sample_text:
- `MPESA` / "M-Pesa C2B (received from)": `{ref} Confirmed. {*}Ksh{amount} received from {name} {phone} on {*}` (port of the deleted `_MPESA_SMS_PATTERN`)
- `MPESA` / "M-Pesa paybill with account": `{ref} Confirmed.{*}Ksh{amount}{*}received from {name} {phone}{*}for account {account}{*}`
- `KCB` / "KCB credit alert": `{*}KES {amount} received from {name} to your account {account}, Ref {ref}{*}`
- `EQUITY BANK` / "Equity credit alert": `{*}received KES {amount} from {name}. Ref: {ref}{*}`

Mark the KCB/Equity ones `is_active=True` but expect the admin to adjust — that's what the unparsed queue + test console are for.

### 3.3 Ingest pipeline — `process_copilot_message(device, payload) -> CopilotMessage`

Single service function; the route is thin. Steps, in order, **one DB transaction per message**:

1. **Idempotency:** `(device_id, client_uuid)` already exists → return existing row (`duplicate`, no side effects). Then `dedupe_hash` seen for this landlord within 7 days → store row as `duplicate` with `error_reason="dedupe_hash hit"`.
2. **Gate:** landlord's `copilot_enabled` and not `copilot_admin_locked`; else store as `rejected` (`error_reason="copilot disabled"`) and tell the device (§4.3 response) so the app can show "paused".
3. **Parse** via §3.1. No template hit → `parse_status='unparsed'`, `match_status='n_a'`, stop (row lands in the admin unparsed queue). Parsed but amount invalid → `rejected`.
4. **Ref dedupe:** if `parsed_ref` and an `MpesaTransaction` with that `reference_number` exists for this landlord → `duplicate` (guards the same payment arriving via two SMSs or a re-forward after code regeneration).
5. **Match tenant:** `parsed_account` → `Tenant.account_number` exact (landlord-scoped, `is_deleted=False`); miss → `parsed_phone` normalised → `Tenant.phone` (normalise both sides the way `mpesa_routes.py:289-292` does); miss → `match_status='unmatched'`.
6. **Create `MpesaTransaction`** (both matched and unmatched): `reference_number=parsed_ref or f"COP-{message.id}"`, `amount`, `tenant_id`, `description=f"Co-pilot | {sender_id} | {parsed_name} | {raw_text[:120]}"`, `status='recorded'` if matched else `'unmatched'`.
7. **If matched, create `Payment`:** `source='co_pilot'`, `payment_ref=_ref_number(...)` (reuse the counter helper pattern), `mpesa_reference=parsed_ref`, `payment_date=sms_received_at.date() if sms_received_at else today`, `notes=f"Co-pilot via {sender_id}. Payer: {parsed_name}."`
   - `copilot_auto_allocate=True` → `status='confirmed'`, then **exactly** the `payment_routes.py:204-217` pattern: `auto_allocate(...)` + `apply_allocations(...)`. Never touch `tenant.balance` directly.
   - `copilot_auto_allocate=False` → `status='pending'`, no allocation, no balance change. `notify(...,'copilot_payment_pending', link="/landlord/payments?status=pending")`.
   - Auto-allocate confirmed payments additionally fire the existing `alert_service.dispatch_alert` + `automation_service.on_payment_recorded` hooks (same as `payment_routes.py:234-239`) so receipts/acknowledgements behave identically to manual entry.
8. **If unmatched:** `notify(...,'copilot_payment_unmatched', link="/landlord/payments?tab=mpesa&status=unmatched")`.
9. **Audit:** `record_audit(actor_user_id=None, landlord_id=..., action="copilot_ingest", entity_type="copilot", entity_id=message.id, description=f"Co-pilot [{device.device_name}] {sender_id}: {outcome summary}")`. (`actor_user_id` is nullable per migration `e1f2a3b4c5d6`; there is no human actor here.)
10. Update `device.last_seen_at`; commit; return the row.

**Error containment:** wrap each message in the batch in its own try/except+rollback; one bad SMS must not fail the batch. Any unexpected exception → store the message as `rejected` with `error_reason` and return per-message status to the app.

---

## 4. Device-facing API (`server/routes/copilot_routes.py` — new blueprint `copilot_bp`, prefix `/api/copilot`)

No `@jwt_required()` anywhere here. Auth = `X-Copilot-Token: <raw device token>` header → helper decorator `@require_copilot_device` that resolves the `CopilotDevice` (active only), 401 otherwise, attaches it to `g`, bumps `last_seen_at`. Register the blueprint in `routes/__init__.py`.

### 4.1 `POST /api/copilot/pair`
Body: `{ agent_code, device_name, device_model?, app_version? }`.
- Look up `Landlord.agent_code` (case-insensitive strip). Miss → 404 generic `"Invalid code"` (don't leak which part failed).
- Landlord's `copilot_enabled` must be True → else 403 `"Co-pilot is not enabled for this account. Enable it in Sahil Settings → Co-pilot first."`
- Create device, return **once**: `{ device_token, landlord_name: company_name, device_id, sender_presets: [...] }` (presets from §5.4 so the app's picker is server-fed but cached).
- `notify` the landlord (`copilot_device_paired`) + `record_audit` — a paired device the landlord didn't expect is the #1 leaked-code tell.
- **Rate limit:** 5 attempts / 15 min / IP (simple in-memory or DB counter) — the agent code is short, brute force must be expensive.

### 4.2 `POST /api/copilot/heartbeat` (device auth)
Body: `{ app_version, sender_ids: [...], queued_count }`. Updates device row. Returns `{ status: 'active'|'revoked', copilot_enabled: bool, latest_version_code, min_supported_version_code, apk_url }` — the app uses this to pause itself, show "disabled by landlord", or prompt an update. Called on app open + daily.

### 4.3 `POST /api/copilot/ingest` (device auth)
Body: `{ messages: [{ client_uuid, sender_id, text, received_at }] }` — **batch** (the app flushes its offline queue here), max 50/batch, max text 1000 chars.
Response 200: `{ results: [{ client_uuid, status: parsed|unparsed|duplicate|rejected, match: matched|unmatched|n_a, payment_ref? , error? }], copilot_enabled }`.
Always 200 when auth passes (per-message outcomes inside), 401 for bad token — the app maps 401 → re-pair screen.

### 4.4 `GET /api/copilot/app/latest` (public, no auth)
`{ version_name, version_code, min_supported_version_code, apk_url, release_notes }` from the `is_latest` release.

### 4.5 `GET /api/copilot/app/download` (public)
Streams the latest APK (`send_file`, `application/vnd.android.package-archive`). Public on purpose: you send clients this one link; there's nothing secret in the APK.

### 4.6 Fix the existing manual-match bug while here
`mpesa_routes.py::match_transaction` (`/transactions/<id>/match`) bumps `tenant.balance` directly (`mpesa_routes.py:585`). Rework it to create the Payment as `pending` **or** run `apply_allocations` per the landlord's `copilot_auto_allocate` — mirror §3.3 step 7. Also set `source='co_pilot'` when the matched `MpesaTransaction` originated from Co-pilot (it has a `CopilotMessage` pointing at it), and back-fill `CopilotMessage.tenant_id/payment_id/match_status='matched'` on that row.

---

## 5. Landlord-facing API (JWT, existing patterns)

Add to `settings_routes.py` (or a `copilot` section within it):

- **`GET /api/settings/copilot`** — `{ enabled, auto_allocate, admin_locked, consented_at, agent_code, devices: [{id, device_name, device_model, app_version, status, last_seen_at, sender_ids}], stats: { messages_7d, unmatched_open, pending_payments } }`. Permission: `settings/view`.
- **`PUT /api/settings/copilot`** — `{ enabled?, auto_allocate? }`. Enabling first time stamps `copilot_consented_at`. If `copilot_admin_locked` → 403 `"Co-pilot has been disabled by the administrator."` Audit both flips with before/after. Permission: `settings/edit`.
- **`DELETE /api/settings/copilot/devices/<id>`** — revoke (set status, `revoked_by='landlord'`, timestamp). Audit. Permission: `settings/edit`.
- **`GET /api/settings/copilot/messages`** — landlord's own `CopilotMessage` log, paginated, filters `parse_status`, `match_status`, `date range`. (Their own forwarded-SMS activity feed; raw text is their own data.)

---

## 6. Landlord portal UI (`client/src/features/landlord/`)

### 6.1 Settings → new "Co-pilot" tab (`settings/CopilotSettings.jsx`)
Follow the existing settings-tab pattern (`GeneralSettings.jsx` / `AccountSettings.jsx` styling: glass cards, `text-white/50` help text).

1. **Enable card** — toggle + consent copy: *"By enabling Co-pilot, payment confirmation SMSs forwarded from your phone will be recorded in Sahil as payments. You can disable this at any time."* First enable → confirm modal, then stamps consent. If `admin_locked`, toggle disabled with an explanatory banner.
2. **Allocation mode card** — radio: *Auto-allocate* ("follows your Settings → Payments priority") vs *Review first* ("payments arrive as Pending; you confirm and allocate each one"). Default: Review first.
3. **Agent code card** — moved here from `AccountSettings.jsx` (remove it there). Generate/regenerate + copy; caption: *"Regenerating stops NEW pairings with the old code. Already-paired devices keep working — revoke them below if needed."*
4. **Paired devices table** — name, model, app version, last seen (relative), configured senders (chips), status; row action: Revoke (confirm dialog).
5. **Recent activity** — last 20 `CopilotMessage` rows: time, sender, amount/status pills (`Parsed·Matched`, `Unmatched`, `Unparsed`, `Duplicate`), linked payment ref. "View all" → filterable list.

New `settingsApiSlice` endpoints for §5; add a `CopilotSettings` cache tag.

### 6.2 Payments page touches
- Source filter/badge already knows `co_pilot` — verify the label renders as "Co-pilot" and add it to any source filter dropdown that hard-codes options (`utils/constants.js`).
- Pending payments list: Co-pilot pending rows show a small phone icon + "via Co-pilot"; ConfirmPaymentModal needs no change (existing confirm+allocate flow).
- M-Pesa transactions tab: "Unmatched" rows from Co-pilot resolve through the existing match flow (now fixed per §4.6).

### 6.3 Notifications
The three new categories render via the existing notifications UI automatically once templates are registered; verify links route correctly (`routePaths.js`).

---

## 7. Admin API (`server/routes/admin_copilot_routes.py` — new blueprint `admin_copilot_bp`, prefix `/api/admin/copilot`)

All endpoints: system-admin JWT (copy decorator usage from `admin_sms_routes.py`). Every mutation → `record_audit` with `entity_type="copilot"`.

| Endpoint | Purpose |
|---|---|
| `GET /overview` | Fleet dashboard: landlords enabled, devices active / stale (no heartbeat > 48 h), messages today/7d, parse-failure %, unparsed open count, unmatched open count, payments (count+sum) via Co-pilot 7d |
| `GET /devices` | All devices, filters: landlord, status, stale; includes landlord company name |
| `POST /devices/<id>/revoke` | Admin kill switch per device (`revoked_by='admin'`) |
| `GET /landlords` | Per-landlord Co-pilot posture: enabled, auto_allocate, locked, device count, last message at, unmatched open |
| `PUT /landlords/<id>` | `{ admin_locked: bool }` — platform-level kill switch; locking also (soft) blocks ingest immediately (§3.3 step 2) |
| `GET /messages` | Global ingest log: filters landlord, sender_id, parse_status, match_status, date range; returns raw_text (admin sees all — this is the audit view) |
| `GET /templates` / `POST /templates` / `PUT /templates/<id>` / `DELETE /templates/<id>` | Parser template CRUD. POST/PUT validate+compile (§3.1 rule 3) and 400 with the compiler's error message on failure. DELETE = soft: set `is_active=False` if any `CopilotMessage` references it |
| `POST /templates/test` | `{ template_text, sample_sms }` → `{ ok, fields?: {amount, ref, name, account, phone}, error? }` — powers the test console; also run automatically against `sample_text` on save |
| `GET /unparsed` | Unparsed queue grouped by `sender_id` with counts + latest examples — "which bank do I need a template for?" |
| `POST /unparsed/<message_id>/retry` | Re-run §3.3 from step 3 on one message (after adding a template). Also `POST /unparsed/retry-all?sender_id=` to drain a sender's queue |
| `GET /releases` / `POST /releases` | List / upload APK (multipart; store under `server/uploads/copilot/`, extract nothing — admin supplies `version_name`, `version_code`, `release_notes`, `is_latest`, `min_supported_version_code`). Setting `is_latest` clears the previous |

### 7.1 Template-from-message flow (the workflow you asked for)
In the unparsed queue, each message has **"Create template"**: opens the template editor pre-filled with `sender_id` and the raw text as both `sample_text` and the starting `template_text`; admin swaps the variable parts for placeholders, hits Test (live extraction preview against the sample), saves, then "Retry all for this sender". **That is the complete new-bank onboarding loop — zero code.**

---

## 8. Admin portal UI (`client/src/features/admin/`)

New sidebar group **"Co-pilot"** (add to `AdminSidebar.jsx` + `routePaths.js` + `AppRoutes.jsx`), pages:

1. **`CopilotOverview.jsx`** — stat tiles (devices active/stale, messages 7d, parse-failure rate, unmatched open, KES via Co-pilot 7d) + latest-messages table + "needs attention" cards (unparsed senders, stale devices).
2. **`CopilotDevices.jsx`** — fleet table (landlord, device, model, version — badge red if `< min_supported`, last seen, senders, status) + revoke action.
3. **`CopilotLandlords.jsx`** — per-landlord posture table + `admin_locked` toggle (confirm dialog: "This immediately stops payment ingestion for X"). Also surface a Co-pilot card inside the existing `LandlordDetail.jsx` drill-down linking here.
4. **`CopilotMessages.jsx`** — global ingest log with the §7 filters; row expand → raw SMS text, parse fields, linked tenant/payment/audit.
5. **`CopilotTemplates.jsx`** — template list; editor drawer with: sender ID input, name, sample SMS textarea, template textarea, placeholder-chip helper row (click `{amount}` to insert), priority, active toggle, **live test panel** (calls `/templates/test` on change, shows extracted fields or error). Second tab: **Unparsed queue** grouped by sender with the "Create template" flow (§7.1) and retry buttons.
6. **`CopilotReleases.jsx`** — upload form (APK file, version name/code, notes, latest/min-supported flags) + release history + copyable public download link.

New `adminCopilotApiSlice.js` following `adminSmsApiSlice.js` conventions.

---

## 9. Failure modes & the built-in mitigations (verify each in review)

| # | Risk | Mitigation (already specified above) |
|---|---|---|
| 1 | Same SMS forwarded twice (queue retry, reinstall) | `client_uuid` unique per device + `dedupe_hash` 7-day window + `parsed_ref` vs `MpesaTransaction` (§3.3 steps 1, 4) |
| 2 | Agent code leaked / brute-forced | Code only pairs (never ingests); pairing rate-limited; landlord notified on every pairing; device list + revoke; admin lock (§4.1) |
| 3 | Stolen/lost phone keeps forwarding | Landlord revoke (settings) or admin revoke; token check on every call |
| 4 | Fake/edited SMS injected from a paired device | Default mode is **pending** review; raw text stored verbatim in the log; ref dedupe; audit trail; landlord confirms before ledgers move |
| 5 | Wrong tenant match | Exact `account_number` only (unique per landlord by constraint), then exact phone; anything fuzzy → unmatched queue, human decides |
| 6 | Bank changes SMS wording | Messages fall to **unparsed** (never mis-parsed silently, since templates are exact-shape); admin queue surfaces it; template edit + retry-all recovers the backlog |
| 7 | Bad template regex hangs the server | Compile-time validation, no nested quantifiers by construction, 100 ms search guard (§3.1) |
| 8 | Ledger corruption | `allocation_service` is the only writer; pending payments touch nothing; the two legacy direct-balance bugs are removed (§1, §4.6) |
| 9 | Reversal/refund SMSs recorded as income | Reversal texts don't match credit templates → unparsed queue; v1 policy: admin/landlord handles reversals manually. Do NOT add a reversal template that creates negative payments |
| 10 | Landlord disabled mid-stream / subscription lapsed | Ingest gate (§3.3 step 2) stores as `rejected` + tells the app to pause; nothing lost — messages stay in the app log |
| 11 | Duplicate with a manually-recorded payment | On pending-confirm, ConfirmPaymentModal already shows tenant context; additionally flag in the pending list when a confirmed payment with same tenant+amount exists within ±2 days (`possible_duplicate: true` from the list endpoint) — badge only, never auto-block |
| 12 | Phone clock skew | `sms_received_at` stored as-reported but `created_at` (server) is authoritative for ordering; payment_date falls back to server date |
| 13 | PII in raw SMS | Raw text visible only to the owning landlord and system admins; not exposed on tenant portal; note for later: retention policy (e.g. prune raw_text after 12 months) — out of scope v1 |
| 14 | Old app versions in the field | Heartbeat reports version; `min_supported_version_code` forces update prompt; admin devices table shows outdated badge |

---

## 10. Migration & seed

1. One Alembic migration: 4 new tables + 4 `landlord_settings` columns (+ server defaults so existing rows get `False`).
2. Seed parser templates (§3.2) — in the migration's `upgrade()` data step or `seed.py` (follow how existing seed data handles idempotency).
3. `seed.py`: give the demo landlord `copilot_enabled=True`, a paired demo device, and a handful of `CopilotMessage` rows in every status so all UIs render with data.

## 11. Tests (pytest, `server/tests/test_copilot_service.py`)

Follow `conftest.py` fixtures. Cover at minimum:
- Template compiler: each placeholder, whitespace tolerance, save-validation rejections, the §3.2 seeds against realistic sample texts.
- Pipeline: parsed+matched-by-account, matched-by-phone, unmatched, unparsed, `client_uuid` replay, `dedupe_hash` replay, `parsed_ref` replay, disabled landlord, admin-locked landlord.
- Ledger: auto-allocate path creates confirmed payment + allocations via the service (assert line-item/`amount_paid` moves and `tenant.balance` consistency); pending path touches **nothing** until confirm.
- Pairing: bad code, disabled landlord, rate limit, token hash round-trip, revoked-device 401.
