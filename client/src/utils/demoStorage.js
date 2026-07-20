const KEY = "sahilpay_demo_mode";

// { active: true } while a landlord/PM is browsing their demo shadow account,
// or null. Mirrors impersonationStorage.js's pattern — read synchronously by
// apiSlice.js's prepareHeaders on every request (see DEMO_MODE_SPEC.md §5.1).
export function getDemoMode() {
  const raw = localStorage.getItem(KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function setDemoMode(state) {
  localStorage.setItem(KEY, JSON.stringify(state));
}

export function clearDemoMode() {
  localStorage.removeItem(KEY);
}

export default { getDemoMode, setDemoMode, clearDemoMode };
