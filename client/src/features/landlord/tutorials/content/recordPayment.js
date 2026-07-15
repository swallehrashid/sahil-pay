import { Wallet } from "lucide-react";
import { ANCHORS } from "../anchors";
import { LANDLORD_ROUTES } from "@/config/routePaths";

export default {
  id: "record-payment",
  title: "Record a payment",
  icon: Wallet,
  duration: "~2 min",
  section: "payments",
  mode: "tour",
  prerequisite: { count: "invoices", tutorialId: "create-invoice", soft: true },
  steps: [
    {
      anchor: ANCHORS.payments.recordButton,
      route: LANDLORD_ROUTES.payments,
      title: "Record what came in",
      body: "Tenant paid you? Click here to record it.",
      advanceOn: { event: "click" },
    },
    {
      anchor: ANCHORS.payments.tenantSelect,
      route: LANDLORD_ROUTES.payments,
      title: "Pick the tenant",
      body: "SahilPay shows what they owe as you pick them.",
    },
    {
      anchor: ANCHORS.payments.amountField,
      route: LANDLORD_ROUTES.payments,
      title: "Enter the amount",
      body: "Enter exactly what they paid — even if it's not the full amount. Partial payments are normal; SahilPay spreads the money across what they owe in your priority order, and any extra becomes credit for next month. (There's a short \"How allocation works\" guide in Help & Tutorials.)",
    },
    {
      anchor: ANCHORS.payments.saveButton,
      route: LANDLORD_ROUTES.payments,
      title: "Save it",
      body: "The allocation preview above already shows where the money is going. Click Record payment and the tenant's balance updates everywhere instantly — reports, their portal, everything.",
    },
    {
      anchor: null,
      route: LANDLORD_ROUTES.payments,
      title: "Manual today, automatic soon",
      body: "Right now you record payments yourself. Once your M-Pesa paybill or till is connected to SahilPay, tenant payments will record themselves the moment they land — see \"Getting paid via M-Pesa\" in Help & Tutorials for how that works.",
    },
  ],
};
