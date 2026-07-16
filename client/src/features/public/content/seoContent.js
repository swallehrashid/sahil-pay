// ---------------------------------------------------------------------------
// Sahil Pay marketing SEO content bank
// ---------------------------------------------------------------------------
// 50 real questions a Kenyan landlord, property manager or caretaker searching
// for rental-management software would type into Google, each with a concise,
// keyword-rich answer. Every section across the public pages (Home, Features,
// Pricing, About, Contact, FAQ) answers at least four of these — this file is
// the single source of that copy so the messaging stays consistent and the
// pages stay dense enough to rank.
//
// Grouped by search intent. `id`s are stable so pages can reference specific
// answers; the FAQ page renders the whole bank by category.

export const SEO_FAQ_CATEGORIES = [
  {
    category: "Getting started",
    questions: [
      { id: "what-is", q: "What is the best rental management software in Kenya?", a: "Sahil Pay is an all-in-one rental and property management platform built for Kenya — it combines M-Pesa rent collection, automated invoicing, a tenant portal, maintenance tracking, team permissions and financial reporting in one place, so landlords stop juggling spreadsheets and WhatsApp messages." },
      { id: "who-for", q: "Who is Sahil Pay for?", a: "Individual landlords, property managers, real-estate agencies and caretakers who manage anything from a single rental unit to thousands of units across many properties." },
      { id: "how-start", q: "How do I start managing my rentals online?", a: "Create a free account, add your properties and units, import or add your tenants, and connect M-Pesa. You can be collecting rent and sending invoices the same day — no installation, it runs in your browser and on mobile." },
      { id: "need-install", q: "Do I need to install anything or buy hardware?", a: "No. Sahil Pay is fully cloud-based and mobile-first — you and your tenants just need a phone or computer with a browser. There is nothing to install and no hardware to buy." },
      { id: "replace-spreadsheets", q: "Can property management software replace my spreadsheets?", a: "Yes. Sahil Pay replaces rent-tracking spreadsheets, paper receipts and scattered M-Pesa SMS with one live system where every unit, tenant, invoice and payment is always up to date and reconciled automatically." },
    ],
  },
  {
    category: "M-Pesa & payments",
    questions: [
      { id: "mpesa", q: "Does Sahil Pay support M-Pesa for rent collection?", a: "Yes — Sahil Pay is M-Pesa native. It supports both Paybill and Till (Buy Goods), STK push prompts, and automatic matching of incoming M-Pesa payments to the right tenant and invoice." },
      { id: "reconcile", q: "How do I reconcile M-Pesa payments to tenants automatically?", a: "Incoming M-Pesa transactions are matched to tenants by account/reference and amount, then allocated to outstanding invoices automatically. Anything that can't be matched is flagged for a one-click manual match." },
      { id: "bank", q: "Can I reconcile bank statement payments too?", a: "Yes. Upload a bank statement and Sahil Pay reconciles the transactions against tenant invoices, so cheque, bank-transfer and cash-deposit rents are tracked alongside M-Pesa." },
      { id: "partial", q: "Can tenants pay rent in partial instalments?", a: "Yes. Sahil Pay handles partial payments, splits a single payment across multiple invoices, and always shows each tenant's exact running balance, arrears or credit." },
      { id: "receipt", q: "Do tenants get an automatic receipt after paying rent?", a: "Yes — every recorded payment generates an instant receipt the tenant can view and download from their portal, and an acknowledgement can be sent automatically by SMS or email." },
      { id: "manual", q: "Can I record cash rent payments manually?", a: "Yes. Cash, cheque or any off-platform payment can be recorded manually with a reference and proof, and it updates the tenant's balance and statement immediately." },
    ],
  },
  {
    category: "Invoicing & rent",
    questions: [
      { id: "auto-invoice", q: "Can I automate monthly rent invoices?", a: "Yes. Set rent once and Sahil Pay generates and sends monthly rent invoices automatically, including recurring utility charges and service fees, so you never have to raise them by hand." },
      { id: "utilities", q: "How do I bill tenants for water and electricity?", a: "Enter meter readings and Sahil Pay turns the consumption into utility line items on the tenant's invoice, using your per-unit rates — water, electricity, garbage and any custom charge." },
      { id: "penalties", q: "Can I charge late-payment penalties automatically?", a: "Yes. Configure penalty rules and Sahil Pay applies late fees to overdue invoices automatically, keeping arrears and penalties clearly itemised." },
      { id: "bulk", q: "Can I invoice all my tenants at once?", a: "Yes — bulk-generate invoices for a whole property or your entire portfolio in one action, then send them by SMS, email or WhatsApp." },
      { id: "deposit", q: "Does it track rent deposits and refunds?", a: "Yes. Deposits are tracked per tenant and reconciled on move-out, with any deductions and refunds recorded on the tenant's statement." },
      { id: "statements", q: "Can I generate tenant statements as PDF?", a: "Yes. Every tenant has a full statement of invoices, payments and balances that you can download as a branded PDF or Excel file at any time." },
    ],
  },
  {
    category: "Tenants & the tenant portal",
    questions: [
      { id: "portal", q: "Is there a tenant portal or app?", a: "Yes. Tenants get their own secure self-service portal to see their balance, invoices, payment history and receipts, submit maintenance requests and receive notices — no app store download required." },
      { id: "tenant-login", q: "How do tenants log in without a password?", a: "Tenants log in with a one-time code (OTP) sent to their phone or email — passwordless and secure, so there are no passwords for them to forget or for you to reset." },
      { id: "balance", q: "How do tenants check how much rent they owe?", a: "Each tenant sees a live balance breakdown in their portal — rent, utilities, penalties, payments and any credit — so there are no disputes about what is owed." },
      { id: "lifecycle", q: "Can I track a tenant's full history?", a: "Yes. Sahil Pay records the complete tenant lifecycle — move-in, unit transfers, lease terms, documents, payments and move-out — with a full shift history per unit." },
      { id: "lease-expiry", q: "Will I get alerts before a lease expires?", a: "Yes. Sahil Pay sends lease-expiry alerts ahead of time so you can renew, adjust rent or plan a vacancy before the unit becomes empty." },
    ],
  },
  {
    category: "Teams, caretakers & permissions",
    questions: [
      { id: "caretaker", q: "Can I give my caretaker limited access?", a: "Yes. Add caretakers and property managers as team members with a fine-grained view/edit permission matrix per module, and scope them to only the properties they manage." },
      { id: "roles", q: "Does it support multiple users and roles?", a: "Yes — landlord/owner, property managers, caretakers and support each get an appropriate, permissioned view. You decide exactly what each person can see and do." },
      { id: "audit", q: "Can I see who did what in my account?", a: "Yes. Every create, edit and delete — by you, your team or support — is written to a full, immutable audit trail, so nothing happens silently." },
      { id: "scope", q: "Can a manager be limited to specific properties?", a: "Yes. Team members can be scoped to specific properties or property groups, so a manager only sees and acts on their assigned portfolio." },
    ],
  },
  {
    category: "Maintenance & operations",
    questions: [
      { id: "maintenance", q: "How do I track maintenance requests?", a: "Tenants log maintenance requests from their portal; you track them by status and category, assign them, and link the cost as an expense — all in one place." },
      { id: "expenses", q: "Can I record property expenses and see profitability?", a: "Yes. Record one-off and recurring expenses per property, categorise them, and Sahil Pay nets them against rent collected to show real income and profitability." },
      { id: "recurring-bills", q: "Can I set up recurring bills and charges?", a: "Yes. Recurring rent, service charges and expenses run automatically on the schedule you set, so nothing is missed month to month." },
      { id: "vacancy", q: "How do I track occupancy and vacancy?", a: "Sahil Pay shows live occupancy and vacancy per property and across your portfolio, so you always know which units are earning and which are empty." },
    ],
  },
  {
    category: "Communications",
    questions: [
      { id: "sms", q: "Can I send rent reminders by SMS?", a: "Yes. Send SMS rent reminders and notices to one tenant or in bulk, using reusable templates with variables like the tenant's name, unit and outstanding balance." },
      { id: "channels", q: "Does it support SMS, email and WhatsApp?", a: "Yes — reach tenants over SMS, email and WhatsApp with templated messages, and track delivery status for each one." },
      { id: "own-sender", q: "Can I send SMS from my own sender ID?", a: "Yes. Connect your own registered sender ID to send under your brand, or use Sahil Pay's shared sender ID and simply top up SMS credits — you choose." },
      { id: "automate-reminders", q: "Can rent reminders be sent automatically?", a: "Yes. Automated reminders can go out on a monthly schedule and on payment, so tenants are nudged and thanked without you lifting a finger." },
    ],
  },
  {
    category: "Reports, accounting & tax",
    questions: [
      { id: "reports", q: "What financial reports does it produce?", a: "Rent-roll, arrears, expenses, occupancy, month-on-month and year-on-year performance, per-property and property-group statements — all generated on demand." },
      { id: "download", q: "Can I download reports as PDF or Excel?", a: "Yes. Every report can be previewed, have its columns customised, and be downloaded as a branded PDF or Excel file for your records or your accountant." },
      { id: "tax", q: "Does Sahil Pay help with rental income tax?", a: "Yes. Reports show rent collected, expenses and net income with a per-property tax rate, and you can download tax receipts and statements to file your rental income tax." },
      { id: "arrears", q: "How do I see which tenants are in arrears?", a: "The arrears report lists every tenant behind on rent, how much they owe and for how long, so you can follow up on the biggest balances first." },
      { id: "letterhead", q: "Can reports carry my company branding?", a: "Yes. Add your logo, company details and signature and every statement, invoice and report comes out on your own letterhead." },
    ],
  },
  {
    category: "Pricing, plans & trial",
    questions: [
      { id: "trial", q: "Is there a free trial and do I need a card?", a: "Yes — every new landlord starts with a free trial and no card or payment details are required to begin." },
      { id: "how-priced", q: "How much does rental management software cost in Kenya?", a: "Sahil Pay is priced per unit per month, so you only pay for what you manage. Small landlords pay little; larger portfolios get lower per-unit rates and custom pricing." },
      { id: "per-unit", q: "Do I pay per unit or a flat fee?", a: "Pricing is per unit per month by default, with volume tiers as you grow. Large portfolios can arrange a flat or custom per-unit rate." },
      { id: "discounts", q: "Are there discounts for paying annually?", a: "Yes. Pay monthly, or save with quarterly and annual billing — longer cycles come with a discount." },
      { id: "cancel", q: "Can I cancel or change my plan anytime?", a: "Yes. Plans move up and down automatically as your unit count changes, and you're never locked in — you can change or leave at any time." },
      { id: "hidden", q: "Are there any hidden fees?", a: "No. You pay your per-unit subscription and only pay extra for SMS credits you choose to buy. Everything else — invoicing, the tenant portal, reports and support — is included." },
    ],
  },
  {
    category: "Security, data & support",
    questions: [
      { id: "secure", q: "Is my rental and tenant data secure?", a: "Yes. Data is encrypted, access is permission-controlled, and every action is audit-logged. Your information is yours and is never sold." },
      { id: "export", q: "Can I export my data if I leave?", a: "Yes. You can download scoped backups of your tenants, units, payments and properties as Excel or PDF at any time — your data is never locked in." },
      { id: "backup", q: "Does Sahil Pay back up my data?", a: "Yes. Your data is safely stored in the cloud and you can generate your own scoped backups whenever you want an offline copy." },
      { id: "support", q: "What kind of support do I get?", a: "Hands-on, consent-based support — our team can assist with onboarding and, only with your permission, step in to help inside your account, with every action logged." },
      { id: "kenya", q: "Is Sahil Pay built specifically for the Kenyan market?", a: "Yes. It's built around M-Pesa, KES currency, the Africa/Nairobi timezone and the way Kenyan landlords actually collect rent and communicate with tenants." },
    ],
  },
  {
    category: "Scale & multi-property",
    questions: [
      { id: "multi", q: "Can I manage multiple properties in one account?", a: "Yes. Manage unlimited properties, group them, and see both per-property and portfolio-wide performance from a single dashboard." },
      { id: "groups", q: "Can I group properties by location or owner?", a: "Yes. Property groups let you organise by estate, location or owner and pull grouped reports across them." },
      { id: "agency", q: "Is it suitable for a property management agency?", a: "Yes. Agencies use team permissions, per-property scoping, per-landlord reporting and custom pricing to manage many owners' portfolios from one place." },
      { id: "grow", q: "Will it scale as I add more units?", a: "Yes. Sahil Pay handles single landlords through to thousands of units, and your plan tier adjusts automatically as your portfolio grows." },
    ],
  },
];

// Flat list of all 50 questions for quick reference / counts.
export const SEO_QUESTIONS = SEO_FAQ_CATEGORIES.flatMap((c) => c.questions);
