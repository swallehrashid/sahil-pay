# Co-Pilot: Landlord Inbox + Sender Scoping — Implementation Spec

**Branch:** `backend-set-up`
**Author context:** written after a live production test on 2026-07-21 where a real
M-Pesa paybill deposit (KES 5,000, account `f2`, ref `UG9MLAk3ML`) was forwarded by
the Co-pilot app, reached the server, and was filed `unparsed` with every field null.

Read this whole file before writing code. Sections are ordered by dependency.

---

## 0. Background — what is already built (DO NOT REBUILD)

The ingest pipeline in `server/services/copilot_service.py` is complete and correct.
Verified by reading the source:

- `compile_template()` / `parse_sms()` — placeholder→regex engine, works. The real
  production SMS was tested against the real template and extracted all four fields
  correctly (`ref`, `amount`, `name`, `account`).
- `_finalize_message()` steps 3–9 — parse, ref-dedupe, tenant match (account number
  first, phone fallback), `MpesaTransaction` creation, `Payment` creation.
- **Auto-allocate already works**: `copilot_service.py:536-548` calls
  `auto_allocate()` + `apply_allocations()` through `allocation_service` (the single
  ledger writer), respecting the landlord's configured priority order, then fires
  `dispatch_alert` and `on_payment_recorded`.
- **Review mode already works**: when `copilot_auto_allocate` is off, the Payment is
  created with `status=pending` and a `copilot_payment_pending` notification fires.

**None of the above needs changing.** It has simply never executed in production,
because parsing fails at step 3 for the reason in §1.

What does NOT exist:
- Any landlord-facing endpoint listing `CopilotMessage` rows. `copilot_routes.py`
  has only device endpoints (`pair`, `heartbeat`, `ingest`, `app/latest`,
  `app/download`). Only admins can list messages, via `admin_copilot_routes.py`.
- Any landlord UI for co-pilot messages. `CopilotSettings.jsx` is pairing + toggles.
- Any body-level filter on what gets retained (§2).

---

## 1. Root cause — sender ID mismatch

`copilot/app/src/main/java/com/sahil/copilot/capture/SmsReceiver.kt:40` captures
`displayOriginatingAddress` — the SMS transport "From" field, i.e. the bold name at
the top of the inbox thread.

For an M-Pesa paybill deposit that value is **`MPESA`**. Safaricom sends the message.

The admin created the parser template under `sender_id = "SAHILPAY"`, because
`SAHILPAY` is the string that appears *inside the body* (`received from SAHILPAY for
account f2`). That is the **paybill account holder name**, not the sender.
`SAHILPAY` is also the landlord's *outbound* FluxSMS sender ID — unrelated to
inbound.

`parse_sms()` (`copilot_service.py:212-218`) filters
`SmsParserTemplate.sender_id == "MPESA"`, finds nothing, returns `(None, None)`,
and `_finalize_message` files the row `unparsed` with null fields.

**Data fix (no code):** the production parser template's `sender_id` must be changed
from `SAHILPAY` to `MPESA`. See §7 Step 1.

---

## 1.5 Second root cause — the template editor can't be used correctly (NEW, required)

After the sender-ID fix above, the landlord retested and it *still* failed. Reading
the actual template they saved (via screenshot) explains why — this is a second,
independent bug and both must be fixed for the feature to work at all.

### 1.5.1 What happened

`CopilotManagement.jsx`'s "Create template" button
(`client/src/features/admin/CopilotManagement.jsx:491-498`) pre-fills only
`sample_text` with the raw SMS and `sender_id`; `template_text` starts **empty**.
The placeholder buttons (`insertPlaceholder`, line 550-552) only **append**
`{amount}` etc. to the end of whatever's in `template_text` — there is no way to
select a span inside the sample and convert it into a placeholder in place. The
admin is expected to hand-retype the entire literal SMS around placeholder tokens,
matching punctuation and whitespace exactly.

The landlord did exactly that, and (predictably, given the tool) left several
variable spans as literal text instead of placeholders:

```
{ref} Confirmed.You have received Ksh{amount} from {name} 0722***518 on 21/7/26 at 5:12 PM  New M-PESA balance is Ksh6,506.75. Download My OneApp on https://saf.cx/lPKcC
```

`0722***518`, `21/7/26`, `5:12 PM`, and `6,506.75` are all hardcoded literals. This
template matches **only that one exact SMS** — every future message has a different
masked phone tail, date, time, and running balance, so it will never match again.
Verified: this exact template against this exact SMS matches; against any other
real SMS of the same shape it will not.

This is why the landlord's second live test still failed even with the sender fix
applied and a template present — the template compiled and was found, but its
literal segments never line up with a second, different message.

### 1.5.2 Fix — inline "select then placeholder-ize" in the template editor

In `TemplateDrawer` (`CopilotManagement.jsx:526` onward), change the Sample SMS
textarea into the authoring surface instead of a separate reference blob:

1. Render `sample_text` in a `<textarea>` (or a contenteditable span-based
   surface — a plain textarea with selection tracking is sufficient) that tracks
   the user's text selection (`selectionStart`/`selectionEnd`).
2. When the admin selects a substring of the sample and clicks a placeholder
   button (`{amount}`, `{ref}`, `{name}`, `{account}`, `{phone}`, `{date}`,
   `{time}`, `{*}`), replace that selected substring with the placeholder token
   **in a working copy**, and keep every other character literal.
3. `template_text` is derived automatically from this working copy — the admin
   never hand-types literal SMS text. Keep the existing raw `template_text`
   textarea visible below it (read-only-by-default with an "edit raw" toggle) so
   power users can still hand-tune, but the default path is select-and-convert.
4. Disable the placeholder buttons (or show a tooltip) when there is no active
   text selection, so a stray click can't silently corrupt the template the way
   `insertPlaceholder` currently does.
5. Keep "Live test" (`handleTest`) working unchanged — it already round-trips
   through `test_template()` server-side and is the right verification step; just
   make sure it runs automatically whenever the derived `template_text` changes,
   not only on manual click, so authoring mistakes surface immediately.
6. Add a short inline hint above the sample box: *"Select the part of the message
   that changes each time (amount, name, phone, date...) and click the matching
   placeholder. Leave everything else as-is — that's the fixed wording this
   template will match on."*

This does not change `compile_template()`, `parse_sms()`, or any backend parsing
logic — it only changes how `template_text` is constructed in the admin UI, so it
is safe alongside everything else in this spec.

### 1.5.3 Clarify: two different M-Pesa message shapes exist

For the record (confirmed with the user) — this is expected behavior, not a bug:
real rent collection will use **paybill/till payments**, which carry an account
number (`"...received from SAHILPAY for account f2..."`). The message the landlord
tested with (`"...received Ksh6,500.00 from RIZIKI MARIARA 0722***518..."`) is
M-Pesa's **personal "send money"** format, which has no account number field at
all — only a masked phone tail that cannot reliably match `Tenant.phone` (three
digits are always missing). Do not attempt to make personal-transfer messages
match by account number; that field structurally does not exist in that message
shape. If a "personal transfer" template is wanted at all, it must fall back to
phone-suffix or name matching and should be treated as lower-confidence than the
paybill template — but building that is **out of scope** for this spec. Only the
paybill/account-number shape is required to work end-to-end.

---

## 2. Layer 2 — body-scoped retention (NEW, required)

Changing the sender to `MPESA` means the app forwards **every** M-Pesa SMS on the
landlord's phone: airtime purchases, personal transfers, utility bills, withdrawals.
`SENDER_PRESETS` (`copilot_routes.py:39`) is deliberately broad-carrier, so this is
inherent to the design, not a bug.

Today those non-rent messages are stored in full in `CopilotMessage.raw_text` and
merely fail to parse. With the landlord inbox in §4 showing unparsed messages, a
landlord would see their own private spending inside their rent portal. Unacceptable.

### 2.1 Requirement

When an incoming message matches **no active template** for its sender, the server
must **not retain the message body**.

Implement in `copilot_service.py::_finalize_message`, in the `if not template:`
branch (currently line 408-414):

```python
if not template:
    msg.parse_status = CopilotParseStatus.unparsed.value
    msg.match_status = CopilotMatchStatus.n_a.value
    msg.template_id = None
    msg.error_reason = None
    # NEW: redact. No active template claimed this message, so it is not a
    # payment notification — it is the landlord's private SMS traffic and we
    # must not retain its contents.
    msg.raw_text = _redact_unmatched(msg.raw_text)
    db.session.flush()
    return
```

### 2.2 `_redact_unmatched()`

Add near `_dedupe_hash`. Keep a *shape* fingerprint useful for admin template
authoring, discard the content:

```python
def _redact_unmatched(raw: str | None) -> str:
    """No template claimed this message. Retain only a redacted shape stub —
    enough for an admin to recognise a message family worth writing a template
    for, never enough to expose the landlord's private SMS content."""
    if not raw:
        return "[redacted: no matching template]"
    head = raw.strip()[:40]
    head = re.sub(r"\d", "#", head)
    return f"[redacted: no matching template] {head}..."
```

Digits are masked so amounts/phones/refs never survive. First 40 chars only.

### 2.3 Admin exemption

Admins currently rely on full unparsed text to author templates. Preserve that path
**opt-in per landlord**, defaulting OFF:

- Add `LandlordSettings.copilot_retain_unmatched` — `Boolean, default=False,
  nullable=False`.
- In `_finalize_message`, skip redaction when `ls.copilot_retain_unmatched` is True.
- Surface it in `CopilotSettings.jsx` as a clearly-worded opt-in:
  *"Help improve payment detection — store unrecognised message text so support can
  add new bank formats. Off by default."*
- Migration required (§6).

### 2.4 Dedupe hash ordering

`_dedupe_hash` is computed in `process_copilot_message` **before** `_finalize_message`
runs, from the original `raw_text`. Redaction happens after. Do not move it —
dedupe must keep working on the true body. Verify with a test that forwarding the
same unmatched SMS twice still yields `duplicate` on the second.

---

## 3. Backend — landlord message endpoints (NEW)

Add to `server/routes/copilot_routes.py`. These are **landlord-session** endpoints,
not device-token endpoints — use the same auth decorator the other landlord routes in
this codebase use (match `settings_routes.py`; do NOT invent a new decorator).

Every query MUST filter `landlord_id == current landlord`. A landlord must never read
another landlord's message by guessing an ID.

### 3.1 `GET /api/copilot/messages`

Query params:
- `status` — `all` (default) | `parsed` | `unparsed` | `duplicate` | `rejected`
- `match` — `all` (default) | `matched` | `unmatched`
- `q` — substring over `parsed_name`, `parsed_ref`, `parsed_account`
- `page`, `per_page` (default 25, max 100)

Order `created_at DESC`. Use the project's existing pagination helper — grep for how
`payment_routes.py` paginates and mirror it exactly.

Response per row:
```json
{
  "id": 1, "sender_id": "MPESA", "created_at": "...", "sms_received_at": "...",
  "parse_status": "parsed", "match_status": "matched",
  "parsed_amount": "5000.00", "parsed_ref": "UG9MLAK3ML",
  "parsed_name": "SAHILPAY", "parsed_account": "f2", "parsed_phone": null,
  "tenant": {"id": 4, "name": "Jane Doe", "unit": "F2"},
  "payment": {"id": 9, "payment_ref": "PAY-1-000009", "status": "confirmed"},
  "error_reason": null,
  "raw_text": "...",
  "raw_text_redacted": false
}
```

`raw_text` rules — this is the landlord's own inbox, so they may read bodies that
parsed. Set `raw_text_redacted: true` when the stored text is a §2.2 stub.

### 3.2 `GET /api/copilot/messages/<id>`

Single row, same shape, plus `template_name` (or null). 404 if not this landlord's.

### 3.3 `GET /api/copilot/messages/summary`

Counts for the tab badge: `{"unparsed": 3, "unmatched": 1, "pending_review": 2}`.
`pending_review` = messages whose linked Payment is `pending`.

### 3.4 No landlord mutation endpoints

Landlords must NOT be able to retry parsing or edit parsed fields — templates are
global/admin-owned and a landlord retry could mutate another landlord's data model
assumptions. Allocation of a `pending` Payment happens through the **existing**
payment review flow, which already works. Link to it; do not duplicate it.

---

## 4. Frontend — new "Co-Pilot" tab under Payments

The landlord Payments page is tabbed already. Add a tab named **Co-Pilot**.
Find the Payments page under `client/src/features/landlord/` and follow its existing
tab pattern exactly — do not restructure the page.

### 4.1 Tab and badge

Label `Co-Pilot`. If `summary.unparsed + summary.unmatched > 0`, show a count badge
using whatever badge component the codebase already uses.

### 4.2 List view

Columns: **Received** (`sms_received_at`, fallback `created_at`), **Sender**,
**Amount** (`parsed_amount`, `—` if null), **Account** (`parsed_account`),
**Reference** (`parsed_ref`), **Tenant** (name + unit, or `Unmatched` chip),
**Status**, and a row action **View**.

Status chip mapping:
| parse/match | chip | tone |
|---|---|---|
| parsed + matched + payment confirmed | `Allocated` | success |
| parsed + matched + payment pending | `Needs review` | warning |
| parsed + unmatched | `No tenant match` | warning |
| unparsed | `Not recognised` | neutral |
| duplicate | `Duplicate` | neutral |
| rejected | `Rejected` | danger |

Filters: status dropdown, match dropdown, search box. Wire to §3.1 params.
Include an empty state and a loading state consistent with the rest of the portal.

**Row menus:** this codebase has a known dropdown/table overflow bug — row-action
menus render clipped inside tables. Use the portal-based pattern already adopted
elsewhere in the app. Grep for the existing fix and reuse it; do not write a new
dropdown.

### 4.3 Detail modal (the core ask)

Clicking **View** opens a modal mirroring the admin's, so the landlord finally sees
what the admin sees:

- **Raw SMS** in a monospace block. If `raw_text_redacted`, replace the block with
  the muted line: *"This message wasn't recognised as a payment, so its contents
  weren't stored."*
- Parsed field grid: Amount, Reference, Name, Account, Phone, Tenant, Payment,
  Error. Render nulls as `—`.
- Contextual footer action:
  - payment pending → **Review & allocate** → existing payment review flow for that
    payment id.
  - payment confirmed → **View payment** → existing payment detail.
  - unmatched → static help text: *"No tenant matched account `f2`. Check that a
    tenant's account number matches the one in this message."*
  - unparsed → *"This message format isn't recognised yet. Contact support if this
    was a rent payment."*

### 4.4 Mobile

The portal is mobile-first. Below `md`, render the list as stacked cards, not a
horizontally-scrolling table. Match the card pattern used elsewhere in the portal.

---

## 5. Tests (required — do not skip)

Add `server/tests/test_copilot_landlord_inbox.py`. Follow the fixture style of the
existing `server/tests/test_copilot_service.py`.

Parsing / scoping:
1. **Real-world regression.** Template `sender_id="MPESA"` with the production
   template text; ingest the exact production SMS:
   `UG9MLAk3ML Confirmed. Ksh5000.00 received from SAHILPAY for account f2 on 21/7/26 at 5:51 PM New account balance is Ksh26,543.42. Amount you can transact within the day is 499,850.00.`
   Assert `parse_status == parsed`, `parsed_amount == 5000.00`, `parsed_account == "f2"`,
   `parsed_ref == "UG9MLAK3ML"`.
2. **Auto-allocate on.** Tenant with `account_number="f2"`, `copilot_auto_allocate=True`
   → Payment `confirmed`, allocations written, tenant balance reduced by 5000.
3. **Review mode.** Same but `copilot_auto_allocate=False` → Payment `pending`,
   **balance unchanged**.
4. **Unmatched.** No tenant with `f2` → `match_status=unmatched`, MpesaTransaction
   created, no Payment.
5. **Redaction.** Ingest a personal SMS (`"You have received Ksh200 from JOHN DOE"`)
   with only the paybill template active → `unparsed` AND `raw_text` contains no
   digits and no `"JOHN"`.
6. **Redaction opt-out.** `copilot_retain_unmatched=True` → `raw_text` preserved.
7. **Dedupe survives redaction.** Same unmatched SMS twice → second is `duplicate`.

Endpoints:
8. Landlord A cannot read landlord B's message (404/403), list and detail.
9. Status/match filters and `q` search return correct subsets.
10. `summary` counts are correct.
11. Unauthenticated request is rejected.

Run the full suite before reporting done — no regressions in `test_copilot_service.py`.

---

## 6. Migration

One Alembic migration for `LandlordSettings.copilot_retain_unmatched`
(`Boolean, nullable=False, server_default false`). Follow the existing migration
style. Ensure it runs clean on a fresh DB and on a DB with existing rows.

---

## 7. Post-implementation manual verification

**Step 1 — rebuild the paybill template using the fixed editor (no deploy needed
for this step once §1.5 ships):**
Admin → Co-Pilot → Templates → open/recreate the paybill template with
`sender_id = MPESA`, using select-then-placeholder-ize on a real paybill sample
(`"...received from SAHILPAY for account f2..."` shape) so `{account}`, `{name}`,
`{ref}`, `{amount}` are true placeholders and nothing else is. Save, then find the
unparsed 5,000 message and hit **Retry**. It should parse and, if a tenant holds
account `f2`, allocate. This validates §1 and §1.5 together.

**Step 2 — end-to-end with real money.** Send a small real **paybill** payment
(not a personal transfer). Confirm:
app forwards → admin shows parsed → **landlord Payments → Co-Pilot tab shows the row**
→ View shows raw SMS + all fields → auto-allocate wrote to the unit ledger.

**Step 3 — noise check.** Buy airtime, or send/receive a personal transfer, on the
co-pilot phone. Confirm the message appears as `Not recognised` **with its body
redacted** (personal-transfer messages are expected to stay unparsed per §1.5.3).

**Step 4 — template robustness check.** Using the new editor, build the paybill
template from one sample message, then retry-test it against a *second*, different
real paybill SMS (different ref/amount/date/time) pasted into the sample box. It
must still match — this is the regression check for the exact failure mode in §1.5.

---

## 8. Out of scope

Do not change: the allocation engine, the placeholder regex compiler, the Kotlin app,
`SENDER_PRESETS`. The admin co-pilot screens ARE in scope, but narrowly — only the
`TemplateDrawer`/`UnparsedQueue` authoring flow described in §1.5. Do not restyle or
restructure anything else in `CopilotManagement.jsx`. Do not build phone-suffix or
name-based matching for personal-transfer messages (§1.5.3) — paybill/account-number
matching only. If something here seems to require touching anything else, stop and
flag it instead.

---

## 9. Add to test suite: template-editor regression (§1.5)

Add to `server/tests/test_copilot_landlord_inbox.py` (or `test_copilot_service.py`
if that's a better fit for a pure parsing test with no HTTP layer):

12. **Two-message robustness.** Compile a template built the *correct* way (account,
    ref, amount, name as placeholders; date/time as `{date}`/`{time}`, not literals)
    against two different real paybill SMS bodies with different ref/amount/date/time
    values. Both must match and extract correctly — this is the regression test for
    the literal-date/time/balance mistake described in §1.5.1.

This is a backend regex test; §1.5's actual fix is frontend-only (how `template_text`
gets constructed), so there is no new backend code path to unit test for §1.5 itself.
Frontend verification of the editor UX is manual (§7 Step 1 and Step 4) unless the
project already has a component-test setup for the admin app — check for one
(`*.test.jsx` near `CopilotManagement.jsx`) before deciding whether to add one.
