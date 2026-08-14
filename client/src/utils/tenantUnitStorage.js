/**
 * Which unit a multi-unit tenant is currently viewing.
 *
 * One person can rent several units — two in a block, or units under different
 * landlords who don't know about each other. Each is a separate tenancy with
 * its own account number, invoices and balance, so the portal shows ONE at a
 * time and this remembers which.
 *
 * Kept in sessionStorage rather than localStorage: it is a view preference for
 * the current sitting, and a shared phone shouldn't reopen on somebody else's
 * unit tomorrow.
 *
 * SECURITY NOTE: this value is a hint, never an authorisation. The server
 * (tenant_portal_routes._get_portal_tenant) independently verifies that the
 * requested tenancy belongs to the same person as the signed-in one, and
 * refuses anything else with a 403. Editing this key by hand achieves nothing.
 */

const KEY = "sahilpay.tenantUnitId";

export function getSelectedTenantId() {
  try {
    const raw = sessionStorage.getItem(KEY);
    return raw ? Number(raw) : null;
  } catch {
    return null;
  }
}

export function setSelectedTenantId(tenantId) {
  try {
    if (tenantId === null || tenantId === undefined) {
      sessionStorage.removeItem(KEY);
    } else {
      sessionStorage.setItem(KEY, String(tenantId));
    }
  } catch {
    /* storage unavailable (private mode) — the portal just defaults each time */
  }
}

export function clearSelectedTenantId() {
  setSelectedTenantId(null);
}
