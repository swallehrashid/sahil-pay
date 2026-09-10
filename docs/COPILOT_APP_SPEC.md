# CO-PILOT ANDROID APP SPEC — Kotlin SMS Forwarder for Sahil Pay

> **Audience:** implementation agent building the app in a NEW separate repo/folder (e.g. `copilot-app/`).
> **Companion docs:** `COPILOT_PLATFORM_SPEC.md` (the backend API this app talks to — §4 there is the contract), `COPILOT_ROLLOUT_TESTING.md`.
>
> **What it does:** runs on the landlord's phone, listens for incoming SMSs from senders
> the landlord selected (MPESA, KCB, Equity Bank, …), and forwards the **raw text** to the
> Sahil backend. It does NOT parse amounts and does NOT decide anything about payments —
> the server does all of that. The app's jobs are: capture reliably, queue offline,
> deliver exactly-once, and show the landlord a truthful log.

---

## 1. Product constraints

- **Distribution:** sideloaded APK sent directly to clients (WhatsApp/link) — NOT Play Store. This means: no Play-policy SMS restrictions apply, but the app must handle "Install unknown apps" onboarding and self-updating (§8).
- **Users are non-technical landlords.** Setup must be: install → paste code → tick banks → done. Every screen in plain language, no jargon.
- **Branding:** "Co-pilot — by Sahil Pay", themed exactly like the Sahil web app (§7).
- **One paired landlord account per install.** Re-pairing replaces the pairing.

## 2. Tech stack (build exactly this — no substitutions without reason)

| Concern | Choice |
|---|---|
| Language / UI | Kotlin, **Jetpack Compose**, Material 3, single-activity |
| Min / target SDK | minSdk 24 (Android 7.0), targetSdk = latest stable |
| Architecture | MVVM + a thin repository layer; Hilt for DI |
| Local DB | **Room** — tables `queued_sms`, `forwarded_log`, `sender_config` |
| Background work | **WorkManager** (network-constrained unique work) for queue flushing + heartbeat |
| HTTP | Retrofit + OkHttp + kotlinx-serialization; TLS only |
| Secrets | Device token in **EncryptedSharedPreferences** (Android Keystore-backed) |
| Config/state | Jetpack DataStore (non-secret prefs: paired landlord name, last heartbeat result) |

## 3. SMS capture — the core

### 3.1 Receiver
- `BroadcastReceiver` on `android.provider.Telephony.SMS_RECEIVED` (permission `RECEIVE_SMS`), manifest-registered with high `android:priority`. Do **not** become the default SMS app; we only observe.
- Reassemble multipart SMSs (`Telephony.Sms.Intents.getMessagesFromIntent`, concatenate bodies in order) — bank confirmations regularly exceed 160 chars; a half message must never be forwarded.
- Extract: `sender` (originating address / alphanumeric ID), `body`, `timestampMillis`.

### 3.2 Filter
- Compare sender against the enabled `sender_config` rows **case-insensitively, trimmed**. Match on exact sender ID (e.g. `MPESA`, `KCB`); also accept the sender when it arrives with a prefix/suffix variant (contains-match toggleable per sender, default exact).
- Non-selected senders: **drop immediately, never stored, never transmitted** — this is the app's privacy promise and must hold.

### 3.3 Enqueue-then-send (never send-then-store)
On every matching SMS:
1. Insert into Room `queued_sms` **synchronously in the receiver** (via `goAsync()` + coroutine, under the 10 s receiver budget): `{ client_uuid: UUID.randomUUID(), sender_id, text, received_at, attempts: 0, state: QUEUED }`.
2. Enqueue a WorkManager unique work `flush-queue` (`ExistingWorkPolicy.KEEP`, constraint `NetworkType.CONNECTED`, backoff exponential 30 s).
The SMS is durable the instant it's stored; delivery is WorkManager's problem. Process death, reboots (WorkManager persists), and airplane mode are all covered by this ordering.

### 3.4 Flush worker
- Reads up to 50 QUEUED rows (server batch max), POSTs `POST /api/copilot/ingest` with `X-Copilot-Token` header.
- Per-message results from the server (`parsed|unparsed|duplicate|rejected` + `match`, `payment_ref`) are written to `forwarded_log` and the rows leave `queued_sms`. **The server's `client_uuid` idempotency makes retries safe — on any ambiguous failure (timeout, 5xx), keep the rows QUEUED and let backoff retry; duplicates are impossible by design, so never drop on uncertainty.**
- HTTP 401 → stop, mark app state UNPAIRED (§6 Pairing screen with an explanatory message). Response `copilot_enabled: false` → keep capturing+queueing but show the PAUSED banner (server currently refuses; user must re-enable in Sahil).
- Also schedule a **periodic** flush (15 min, network-constrained) as a safety net for missed connectivity callbacks, plus flush on app open.

### 3.5 Battery reality (document in-app, not just code)
Manifest receivers for SMS still fire in Doze on stock Android, but aggressive OEMs (Xiaomi/Oppo/Tecno/Infinix — common in Kenya) kill background apps. Mitigations, all required:
- Onboarding step: request **ignore battery optimizations** (`ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`) with a plain-language explanation.
- A persistent low-priority **foreground service notification** option ("Keep Co-pilot alive" toggle in Settings, default ON): tiny ongoing notification "Co-pilot is protecting your payments ✓". On these OEMs this is the single most effective survival tool.
- Home screen shows "last SMS seen at …" so a silently-killed app is visually obvious.

## 4. Data model (Room)

```
queued_sms:    id, client_uuid (unique), sender_id, text, received_at, attempts, state(QUEUED|SENDING)
forwarded_log: id, client_uuid, sender_id, text_snippet(first 120 chars), received_at, forwarded_at,
               server_status(parsed|unparsed|duplicate|rejected), match_status, payment_ref?, error?
sender_config: id, sender_id, enabled, is_custom, match_mode(EXACT|CONTAINS)
```
`forwarded_log` keeps full history capped at 500 rows (prune oldest). Snippet only — full raw text lives on the server; the phone shouldn't be a second PII store.

## 5. API client (contract = platform spec §4)

| Call | When |
|---|---|
| `POST /pair { agent_code, device_name, device_model, app_version }` | Pairing screen. Store `device_token` (encrypted), `landlord_name`, seed `sender_config` from returned `sender_presets` |
| `POST /ingest { messages:[...] }` + token header | Flush worker |
| `POST /heartbeat { app_version, sender_ids, queued_count }` | App open + daily periodic work. Response drives PAUSED/REVOKED banners and the update prompt (`latest_version_code`, `min_supported_version_code`, `apk_url`) |
| `GET /app/latest` (no auth) | Update check fallback pre-pairing |

Base URL: `BuildConfig.SAHIL_BASE_URL` (debug → local/staging, release → production domain).

## 6. Screens (5 total — keep it this small)

1. **Onboarding/Pairing** — logo, 3 bullet explainer, then: paste agent code (monospace field, paste button), device name (prefilled `Build.MODEL`), Pair button → success animation → permission steps as a checklist (SMS permission → battery exemption → notifications permission on 13+). Error states verbatim from server ("Co-pilot is not enabled for this account…").
2. **Home** — status card: landlord company name, big state pill `ACTIVE ✓ / PAUSED ⏸ / UNPAIRED ⚠ / UPDATE REQUIRED ⬆`, queued count, last SMS captured (relative time), last successful forward. Below: last 5 log entries. This screen must answer "is it working?" in one glance.
3. **Senders** — preset checklist (from pairing response: MPESA, KCB, Equity Bank, Co-op Bank, NCBA, Absa, Family Bank, DTB, Stanbic, I&M) + "Add custom sender" row (text input + exact/contains toggle). Changes sync on next heartbeat.
4. **Activity Log** — the `forwarded_log`, newest first: sender chip, snippet, time, status pill (`Forwarded ✓ matched`, `Forwarded ✓ needs review`, `Queued ⏳`, `Duplicate ⧉`, `Not recognized ?` for unparsed, `Rejected ✗`), payment ref when present. Filter chips by status. Pull-to-refresh triggers a flush.
5. **Settings** — paired account info; Unpair (confirm dialog; wipes token + queue, keeps log); "Keep alive" foreground-service toggle; battery-exemption shortcut; version + "Check for updates"; link "Manage in Sahil" (opens the web portal Co-pilot settings URL).

## 7. Theming — must visually read as Sahil

Port the tokens from `client/src/index.css` into a Compose theme (single dark theme, no light mode — the web app is dark-only):

```kotlin
// colors.kt — Sahil design tokens
val Primary900 = Color(0xFF0F0246)   // app background (deep luxury navy)
val Primary950 = Color(0xFF08011F)
val Primary700 = Color(0xFF160653)   // elevated surfaces
val Primary500 = Color(0xFF2A1B6B)
val Secondary  = Color(0xFFB95F7B)   // muted rose — accents, primary buttons
val Third      = Color(0xFF200497)   // vibrant indigo — highlights, active states
val OnSurface  = Color.White.copy(alpha = 0.90f)
val OnSurfaceDim = Color.White.copy(alpha = 0.50f)
```

- Background `Primary900`; cards = `Primary900` at ~40% over `Primary950` with a `White 10%` border, 16 dp corner radius (the web `.glass` card look).
- Buttons: filled `Secondary`; status ACTIVE pill uses `Third` glow, PAUSED amber, error rose.
- Typography: **Inter** (bundle the font), weights 400/500/600 — matches `--font-sans`.
- Subtle fade-in-up on screen entry (mirrors the web's `--animate-fade-in-up`); don't overdo motion.
- App icon: Sahil mark on `Primary900` (asset to be provided; placeholder = "S" monogram with `Secondary` accent).

## 8. Self-update (sideload world)

- Daily heartbeat (and Settings → Check for updates) compares `BuildConfig.VERSION_CODE` to `latest_version_code`.
- Newer available → Home banner "Update available"; `< min_supported_version_code` → **blocking** full-screen prompt (capture/queue continues; forwarding of new batches may be refused by the server, say so honestly).
- Update flow: download APK from `apk_url` via DownloadManager → `REQUEST_INSTALL_PACKAGES` → fire `ACTION_VIEW` install intent. First time, walk the user through the "allow from this source" system screen with an illustration.
- **Signing discipline (critical):** one release keystore, created once, backed up twice (password manager + offline). Updates install only over the same signature — a lost keystore means every client must uninstall/reinstall and re-pair. Document keystore path/alias in the app repo's README; never commit it.

## 9. Permissions manifest (complete list — nothing more)

`RECEIVE_SMS` (core), `INTERNET`, `ACCESS_NETWORK_STATE`, `POST_NOTIFICATIONS` (13+), `FOREGROUND_SERVICE` (+ `FOREGROUND_SERVICE_DATA_SYNC` on 34+, keep-alive), `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`, `REQUEST_INSTALL_PACKAGES` (self-update). Explicitly NOT: `READ_SMS` (we never read the inbox/history — only live broadcasts; easy trust win to state in onboarding), `SEND_SMS`, contacts, location.

## 10. Security & privacy checklist

- Device token only in EncryptedSharedPreferences; never logged; wiped on unpair.
- TLS only; `android:usesCleartextTraffic="false"` (debug builds may whitelist the dev host via network security config).
- Only selected senders ever leave the phone (§3.2); log stores snippets, not full texts (§4).
- No analytics/crash SDKs in v1 (each is a data processor you'd have to explain to clients). Errors visible via the Activity Log + server-side ingest log.
- Screens contain payment data → `FLAG_SECURE` optional, skip in v1 (landlords screenshot their own data legitimately).

## 11. Build & delivery

- Modules: single `:app` module; packages `capture/`, `queue/`, `api/`, `ui/`, `data/`.
- `versionName`/`versionCode` bumped every release; `versionCode` is what the update check compares.
- Release build: R8 enabled, signed with the release keystore, output `copilot-vX.Y.Z.apk`.
- Ship path: build → admin portal → Co-pilot → Releases → upload with matching `version_code` → send clients the public download link (`/api/copilot/app/download`) — thereafter the app self-updates.

## 12. Definition of done (app side)

1. Fresh install → pair against staging → tick MPESA → send a test SMS from another phone → appears in Sahil as a pending payment, log shows `Forwarded ✓`.
2. Airplane mode → receive 3 SMSs → log shows 3 × `Queued ⏳` → network on → all forwarded within a minute, no duplicates on the server (`client_uuid` respected across a forced retry).
3. Reboot phone with a non-empty queue → queue survives and flushes without opening the app.
4. Revoke the device from the Sahil portal → next flush/heartbeat flips the app to UNPAIRED with a clear message; no crash, queue preserved.
5. Disable Co-pilot in portal → app shows PAUSED; re-enable → resumes without re-pairing.
6. Upload a higher `version_code` release → app prompts to update within a day; update installs over the old version keeping pairing.
7. A non-selected sender's SMS never appears in Room, logs, or network traffic (verify with an inspector).
