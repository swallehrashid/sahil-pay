import { Users } from "lucide-react";
import { ANCHORS } from "../anchors";
import { LANDLORD_ROUTES } from "@/config/routePaths";

export default {
  id: "add-tenant",
  title: "Add a tenant",
  icon: Users,
  duration: "~2 min",
  section: "setup",
  // Permission module that gates this tutorial. Drives the Tenants screens.
  module: "tenants",
  mode: "tour",
  prerequisite: { count: "units", tutorialId: "add-units" },
  steps: [
    {
      anchor: ANCHORS.sidebar.tenants,
      route: LANDLORD_ROUTES.dashboard,
      title: "Open Tenants",
      body: "Click Tenants in the sidebar.",
      mobileBody: "Open the ☰ menu and tap Tenants.",
      advanceOn: { event: "click" },
    },
    {
      anchor: ANCHORS.tenants.addButton,
      route: LANDLORD_ROUTES.tenants,
      title: "Add a tenant",
      body: "Click here to add a tenant.",
      advanceOn: { event: "click" },
    },
    {
      anchor: ANCHORS.tenants.form,
      route: LANDLORD_ROUTES.tenants,
      title: "Fill in their details",
      body: "Enter the tenant's name and phone number, and assign them to a vacant unit.",
    },
    {
      anchor: ANCHORS.tenants.phoneField,
      route: LANDLORD_ROUTES.tenants,
      title: "Why the phone number matters",
      body: "The phone number matters: it's where the tenant receives SMS from you, and it's how they log in to their own tenant portal — they get a one-time code by SMS, no password to forget. They can view their balance, invoices and receipts there, which saves you a lot of \"how much do I owe?\" calls.",
    },
    {
      anchor: ANCHORS.tenants.unitSelect,
      route: LANDLORD_ROUTES.tenants,
      title: "One unit per tenant",
      body: "A tenant occupies exactly one unit; moving them later is supported with a full history.",
    },
    {
      anchor: ANCHORS.tenants.saveButton,
      route: LANDLORD_ROUTES.tenants,
      title: "Save it",
      body: "Save the tenant. They're now part of your portfolio.",
    },
  ],
};
