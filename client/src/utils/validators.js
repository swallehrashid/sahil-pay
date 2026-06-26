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

export function isValidPhone(value) {
  if (!value) return false;
  return /^\+?[0-9]{9,15}$/.test(String(value).replace(/\s/g, ""));
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
  isDateOnOrAfter,
  validateMoneyField,
  validateRequired,
};
