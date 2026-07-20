# Consent-Based Impersonation

How a SahilPay system admin gets temporary, audited access to operate a
landlord's account — and why it is a consent workflow, never a silent backdoor.

> Verified end-to-end on 2026-07-04: request → grant → scoped access → audited
> write → revoke → access denied. Every impersonated action is recorded in
> `audit_logs` with the admin as actor and marked `[Impersonating landlord #<id>]`.

---

## 1. Principle

An admin can never reach a landlord's data by default. To operate an account
the admin must **request** access and the **landlord must explicitly grant it**.
The grant is time-boxed and revocable by either side, and every action taken
during the session is written to the immutable audit trail with the admin (not
the landlord) as the actor.

## 2. Lifecycle

```
   admin              ImpersonationRequest.status            landlord
   ─────                                                     ────────
   POST /request  ─────────────►  pending  ──── notified (in-app) ───►
                                     │
                        landlord grants │ denies
                                     ▼         ▼
                                 granted     revoked
                                     │
        admin operates account (X-Impersonate-Landlord header)
                                     │
             admin revokes │ landlord revokes │ expires_at passes
                                     ▼
                              revoked / expired
```

| Status    | Meaning                                                        |
|-----------|---------------------------------------------------------------|
| `pending` | Requested by admin, awaiting landlord's decision.             |
| `granted` | Landlord consented. Admin may operate until revoked/expired.  |
| `revoked` | Ended — by admin revoke, or landlord deny/revoke.             |
| `expired` | `expires_at` passed before/while granted (auto).             |

## 3. Duration

- Set at request time by `duration_hours` in the request body.
- **Default: 24 hours** (`_DEFAULT_GRANT_HOURS` in `routes/admin_impersonation_routes.py`).
- `expires_at = requested_at + duration_hours` is stamped when the request is created.
- The resolver (`utils.active_impersonation`) only honors a grant while
  `expires_at > now`, so access self-terminates at the deadline even if nobody
  revokes it. A grant that expires before the landlord acts can no longer be granted.

## 4. How a session actually works (technical)

1. The admin "enters" a granted session from the admin **Impersonation** page.
   The frontend stores the target landlord id (`utils/impersonationStorage`) and
   resets the RTK-Query cache so one target never sees another's cached data.
2. From then on, **every** API request carries the header
   `X-Impersonate-Landlord: <landlord_id>` (injected in `store/apiSlice.js`).
   The admin's JWT still identifies them as `system_admin` — the token is not swapped.
3. On the server, `utils.current_landlord_id()` calls `active_impersonation()`
   first. That function returns a live grant **only if**:
   - the caller's role is `system_admin`, **and**
   - the header (or an `impersonate_landlord_id` JWT claim) is present, **and**
   - a matching `ImpersonationRequest` exists with `status = granted` and
     `expires_at > now`.
   When it resolves, `current_landlord_id()` returns the **impersonated
   landlord's** id, so every landlord-scoped query transparently reads/writes
   that landlord's data. With no valid grant, an admin has *no* landlord scope
   and landlord routes return **403**.

## 5. Audit guarantees

Every create/update/delete flows through one of two audit chokepoints, and
**both** stamp impersonated actions:

- `utils.audit()` — used by most landlord routes.
- `services.audit_service.record_audit()` — used by CRUD routes that already
  hold the actor/landlord in hand (e.g. properties, tenants, payments).

For an impersonated action, the row records:

- `actor_user_id` = the **admin's** user id (never the landlord's),
- `landlord_id` = the **target** landlord,
- `description` prefixed with `[Impersonating landlord #<id>]`.

The request/grant/deny/revoke steps themselves are also audited
(`admin_impersonation_request`, `landlord_grant_impersonation`,
`landlord_deny_impersonation`, `admin_impersonation_revoke`).

### Reviewing impersonation activity

In the admin **Master Audit** page:
- tick **"Impersonation actions only"** to filter to marked rows, or
- spot the amber **Impersonated** badge next to any impersonated action, and
- combine with the **Actor type**, **Landlord**, **Activity**, and date filters.

## 6. Security guarantees

- **No request → no access.** An admin cannot act as a landlord without a row in
  `status = granted`.
- **Consent is explicit.** Only the landlord can move a request to `granted`.
- **Time-boxed.** Grants auto-expire at `expires_at`.
- **Revocable by both sides**, at any time.
- **Fully attributable.** The admin's identity is preserved as the actor on
  every action; nothing is attributed to the landlord.
- **Isolated cache.** Entering/exiting a session resets client caches so data
  never leaks across targets.

## 7. API reference

**Admin** (`/api/admin/impersonation`, `system_admin` only)

| Method & path                         | Purpose                                  |
|---------------------------------------|------------------------------------------|
| `POST /request`                       | Request access. Body: `landlord_id`, `reason`, `duration_hours?` (default 24). |
| `GET  /requests`                      | List this admin's requests. Filters: `status`, `landlord_id`. |
| `POST /requests/<id>/revoke`          | End an active session / cancel a pending request. |

**Landlord** (`/api/admin/impersonation/landlord`, landlord/PM only)

| Method & path                         | Purpose                                  |
|---------------------------------------|------------------------------------------|
| `GET  /pending`                       | Outstanding (non-expired) requests awaiting consent. |
| `POST /requests/<id>/grant`           | Consent — moves the request to `granted`. |
| `POST /requests/<id>/deny`            | Refuse — moves the request to `revoked`. |

**Operating the account:** send `X-Impersonate-Landlord: <landlord_id>` on
normal landlord API calls while a grant is active.

## 8. Frontend touchpoints

- **Admin → Impersonation** (`features/admin/Impersonation.jsx`): request access,
  see request status, **Enter session**, **Revoke**.
- **AdminImpersonationBanner** (`features/admin/components/`): shows the live
  session while impersonating and lets the admin exit.
- **Landlord → Settings → Impersonation** (`features/landlord/settings/ImpersonationRequests.jsx`):
  the landlord grants/denies pending requests. Linked from the in-app
  notification the admin's request generates.
