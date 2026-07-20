// THE anchor registry — every data-tour id used by a tutorial step, in one place.
// (ONBOARDING_TUTORIALS_SPEC.md §5.4 / §10.1). If you move or rename an element that
// carries a data-tour attribute, keep the attribute (grep the ANCHORS constant, not the
// raw string) and re-run the affected tutorial — a missing anchor degrades to a centered
// card rather than breaking (see TourOverlay.jsx), but it's worth keeping tidy.
export const ANCHORS = {
  sidebar: {
    dashboard: "sidebar-dashboard",
    properties: "sidebar-properties",
    units: "sidebar-units",
    tenants: "sidebar-tenants",
    invoices: "sidebar-invoices",
    payments: "sidebar-payments",
    utilities: "sidebar-utilities",
    reports: "sidebar-reports",
    communications: "sidebar-communications",
    notifications: "sidebar-notifications",
    settings: "sidebar-settings",
    tutorials: "sidebar-tutorials",
  },
  dashboard: {
    kpiCards: "dashboard-kpi-cards",
    checklist: "dashboard-checklist",
  },
  properties: {
    addButton: "properties-add",
    form: "properties-form",
    saveButton: "properties-save",
  },
  units: {
    addButton: "units-add",
    form: "units-form",
    propertySelect: "units-property-select",
    saveButton: "units-save",
  },
  tenants: {
    addButton: "tenants-add",
    form: "tenants-form",
    unitSelect: "tenants-unit-select",
    phoneField: "tenants-phone-field",
    saveButton: "tenants-save",
  },
  invoices: {
    addButton: "invoices-add",
    categoriesButton: "invoices-categories-button",
    tenantSelect: "invoices-tenant-select",
    lineItemsArea: "invoices-line-items-area",
    saveButton: "invoices-save",
  },
  utilities: {
    categoriesButton: "utilities-categories-button",
    recordButton: "utilities-record-button",
  },
  payments: {
    recordButton: "payments-record-button",
    tenantSelect: "payments-tenant-select",
    amountField: "payments-amount-field",
    saveButton: "payments-save",
  },
  reports: {
    list: "reports-list",
  },
  communications: {
    composeButton: "communications-compose-button",
    templatesTab: "communications-templates-tab",
    log: "communications-log",
  },
  settings: {
    general: "settings-nav-general",
    smsProvider: "settings-nav-sms-provider",
    mpesa: "settings-nav-mpesa",
  },
};

export default ANCHORS;
