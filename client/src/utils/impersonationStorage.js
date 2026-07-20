const KEY = "sahilpay_impersonation_target";

// { landlordId, companyName } while a system_admin is actively operating a
// granted account, or null. Mirrors tokenStorage.js's pattern — read
// synchronously by apiSlice.js's prepareHeaders on every request.
export function getImpersonationTarget() {
  const raw = localStorage.getItem(KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function setImpersonationTarget(target) {
  localStorage.setItem(KEY, JSON.stringify(target));
}

export function clearImpersonationTarget() {
  localStorage.removeItem(KEY);
}

export default { getImpersonationTarget, setImpersonationTarget, clearImpersonationTarget };
