// Affiliate referral-code capture (AFFILIATE_PROGRAM_SPEC.md §11.2). A visitor
// may land on any public page via a `?ref=CODE` share link, then browse
// elsewhere (e.g. Pricing) before registering — so the code is captured on
// EVERY public page load (see PublicLayout.jsx) and persisted, not just read
// once on the registration form.
const KEY = "sahil_ref";

export function captureReferralFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const ref = params.get("ref");
  if (ref) {
    try {
      localStorage.setItem(KEY, ref.trim().toUpperCase());
    } catch {
      // localStorage unavailable (private browsing) — the code still works if
      // the visitor registers within the same page load via the URL param.
    }
  }
}

export function getStoredReferral() {
  try {
    return localStorage.getItem(KEY) || "";
  } catch {
    return "";
  }
}

export default { captureReferralFromUrl, getStoredReferral };
