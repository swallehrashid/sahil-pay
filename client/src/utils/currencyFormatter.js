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

export default formatCurrency;
