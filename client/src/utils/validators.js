// Client-side validation mirroring the backend's Marshmallow/Pydantic rules (Section 1.4/1.5
// of the schema spec). These run before submit so a bad write never reaches the API.

export function isRequired(value) {
  return value !== undefined && value !== null && String(value).trim() !== "";
}

export function isNonNegativeAmount(value) {
  if (value === "" || value === null || value === undefined) return false;
  const n = Number(value);
  return Number.isFinite(n) && n >= 0;
}

export function isValidEmail(value) {
  if (!value) return true; // most email fields are optional platform-wide
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

// Mirrors server/services/phone_service.py: 07…, 01…, 7…, 1…, 254… and +254… are
// one number, stored as 254XXXXXXXXX. Returns null for anything that is not a
// Kenyan mobile number.
export function toKenyanPhone(value) {
  let digits = String(value ?? "").replace(/\D/g, "");
  if (digits.length === 10 && digits.startsWith("0")) digits = `254${digits.slice(1)}`;
  else if (digits.length === 9 && /^[17]/.test(digits)) digits = `254${digits}`;
  return /^254[17]\d{8}$/.test(digits) ? digits : null;
}

export const PHONE_HINT = "07XX XXX XXX or 254 7XX XXX XXX — saved as 2547XXXXXXXX";
export const PHONE_ERROR = "Enter a Kenyan mobile number, e.g. 0712 345 678 or 254712345678";

export function isValidPhone(value) {
  return toKenyanPhone(value) !== null;
}

export function isDateOnOrAfter(laterDate, earlierDate) {
  if (!laterDate || !earlierDate) return true;
  return new Date(laterDate) >= new Date(earlierDate);
}

// Returns an error string, or null when valid — matches the backend rule that amounts
// must be >= 0 unless explicitly a credit/adjustment.
export function validateMoneyField(value, { allowZero = true, required = true } = {}) {
  if (!isRequired(value)) return required ? "Amount is required" : null;
  if (!isNonNegativeAmount(value)) return "Enter a valid, non-negative amount";
  if (!allowZero && Number(value) === 0) return "Amount must be greater than zero";
  return null;
}

export function validateRequired(value, label = "This field") {
  return isRequired(value) ? null : `${label} is required`;
}

export default {
  isRequired,
  isNonNegativeAmount,
  isValidEmail,
  isValidPhone,
  toKenyanPhone,
  isDateOnOrAfter,
  validateMoneyField,
  validateRequired,
};
