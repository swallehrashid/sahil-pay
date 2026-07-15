import { Receipt } from "lucide-react";
import { ANCHORS } from "../anchors";
import { LANDLORD_ROUTES } from "@/config/routePaths";

export default {
  id: "create-invoice",
  title: "Create an invoice",
  icon: Receipt,
  duration: "~3 min",
  section: "billing",
  mode: "tour",
  prerequisite: { count: "tenants", tutorialId: "add-tenant" },
  steps: [
    {
      anchor: ANCHORS.invoices.addButton,
      route: LANDLORD_ROUTES.invoices,
      title: "New invoice",
      body: "Click here to bill a tenant.",
      advanceOn: { event: "click" },
    },
    {
      anchor: ANCHORS.invoices.tenantSelect,
      route: LANDLORD_ROUTES.invoices,
      title: "Who are you billing?",
      body: "Pick the tenant. Their unit's rent comes in automatically.",
    },
    {
      anchor: ANCHORS.invoices.lineItemsArea,
      route: LANDLORD_ROUTES.invoices,
      title: "Line items",
      body: "An invoice is a list of lines — one per charge category: rent, water, garbage… Add whatever applies this month. Each line remembers its category and pocket, which is what makes your reports exact.",
    },
    {
      anchor: ANCHORS.invoices.saveButton,
      route: LANDLORD_ROUTES.invoices,
      title: "Send it",
      body: "Save the invoice. The tenant can see it instantly in their portal, and you can send them an SMS about it from Communications.",
    },
    {
      anchor: null,
      route: LANDLORD_ROUTES.invoices,
      title: "You won't do this by hand forever",
      body: "Once you're comfortable, Settings → General has automation that can generate monthly invoices for every occupied unit automatically. Worth switching on after your first manual month.",
    },
  ],
};
