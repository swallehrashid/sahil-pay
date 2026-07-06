import { DEFAULT_CURRENCY } from "./constants";

// Every monetary figure on the platform renders through this — never format money inline.
export function formatCurrency(amount, currency = DEFAULT_CURRENCY) {
  const value = Number(amount ?? 0);
  const formatted = new Intl.NumberFormat("en-KE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number.isFinite(value) ? value : 0);
  return `${currency} ${formatted}`;
}

export function formatCompactCurrency(amount, currency = DEFAULT_CURRENCY) {
  const value = Number(amount ?? 0);
  const formatted = new Intl.NumberFormat("en-KE", {
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(Number.isFinite(value) ? value : 0);
  return `${currency} ${formatted}`;
}

// #10 — balance display convention. A balance a tenant OWES renders as a plain
// positive number (no sign); an advance/credit (overpayment) renders negative.
// Internally the ledger uses the opposite sign (negative = owed, positive = advance),
// so we negate the stored value for display. Pass the raw ledger balance in.
export function formatBalance(internalBalance, currency = DEFAULT_CURRENCY) {
  const owed = -Number(internalBalance ?? 0); // owed > 0, advance < 0
  return formatCurrency(Object.is(owed, -0) ? 0 : owed, currency);
}

export default formatCurrency;
