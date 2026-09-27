import { CheckCheck } from "lucide-react";
import { ANCHORS } from "../anchors";
import { LANDLORD_ROUTES } from "@/config/routePaths";

export default {
  id: "review-queued-charges",
  title: "Approve queued charges and invoice the month",
  icon: CheckCheck,
  duration: "~3 min",
  section: "billing",
  // Whoever can bill — the office / secretary.
  module: "invoices",
  mode: "tour",
  steps: [
    {
      anchor: ANCHORS.sidebar.invoices,
      route: LANDLORD_ROUTES.dashboard,
      title: "Open Invoices",
      body: "Click Invoices in the sidebar.",
      mobileBody: "Open the ☰ menu and tap Invoices.",
      advanceOn: { event: "click" },
    },
    {
      anchor: ANCHORS.invoices.queueTab,
      route: LANDLORD_ROUTES.invoices,
      title: "Queued charges",
      body: "Meter readings and other charges waiting for an invoice live here. Click the tab.",
      advanceOn: { event: "click" },
    },
    {
      anchor: ANCHORS.invoices.reviewSection,
      route: LANDLORD_ROUTES.invoices,
      title: "Review what the caretaker sent",
      body: "Tick the ones that look right and Approve selected, or Approve all at once. Reject a misread meter — it will never be billed.",
    },
    {
      anchor: ANCHORS.invoices.approvedSection,
      route: LANDLORD_ROUTES.invoices,
      title: "Approved charges wait for the next invoice",
      body: "Everything approved goes onto the unit's next monthly invoice together with the rent and any unpaid balance carried forward — one invoice per tenant.",
    },
    {
      anchor: ANCHORS.invoices.runMonthly,
      route: LANDLORD_ROUTES.invoices,
      title: "Invoice the month",
      body: "On the 1st this runs automatically if the account owner switched it on. You can also run it now: pick rent, approved charges, or both.",
    },
  ],
};
