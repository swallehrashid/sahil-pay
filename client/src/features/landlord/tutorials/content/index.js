import welcomeOverview from "./welcomeOverview";
import createProperty from "./createProperty";
import addUnits from "./addUnits";
import addTenant from "./addTenant";
import chargeCategories from "./chargeCategories";
import createInvoice from "./createInvoice";
import recordPayment from "./recordPayment";
import paymentsAndMpesa from "./paymentsAndMpesa";
import allocation from "./allocation";
import communications from "./communications";
import reports from "./reports";

// Ordered registry of every tutorial (ONBOARDING_TUTORIALS_SPEC.md §7). Section order here
// drives both the hub page's card order and the onboarding sequence's picks.
export const TUTORIALS = [
  welcomeOverview,
  createProperty,
  addUnits,
  addTenant,
  chargeCategories,
  createInvoice,
  recordPayment,
  paymentsAndMpesa,
  allocation,
  communications,
  reports,
];

export const TUTORIALS_BY_ID = Object.fromEntries(TUTORIALS.map((t) => [t.id, t]));

// §7.0 — the first-login guided setup. Reports/allocation/mpesa are hub-only — keep first
// contact to the essentials.
export const ONBOARDING_SEQUENCE = [
  "welcome-overview",
  "create-property",
  "add-units",
  "add-tenant",
  "charge-categories",
  "create-invoice",
  "record-payment",
  "communications",
];

// Hub page section grouping + display order (§6.4).
export const SECTIONS = [
  { key: "setup", label: "Getting set up" },
  { key: "billing", label: "Billing" },
  { key: "payments", label: "Payments" },
  { key: "communication", label: "Communication" },
  { key: "reports", label: "Reports" },
];

export function getTutorial(id) {
  return TUTORIALS_BY_ID[id] ?? null;
}
