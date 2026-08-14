import { LayoutDashboard } from "lucide-react";
import { ANCHORS } from "../anchors";
import { LANDLORD_ROUTES } from "@/config/routePaths";

export default {
  id: "welcome-overview",
  title: "A quick look around",
  icon: LayoutDashboard,
  duration: "~1 min",
  section: "setup",
  // Permission module that gates this tutorial. Explains the product itself — no module gates it.
  module: null,
  mode: "tour",
  steps: [
    {
      anchor: null,
      route: LANDLORD_ROUTES.dashboard,
      title: "Your dashboard",
      body: "This is your home base. Every number you see here — collections, arrears, occupancy — updates live as you work. Let's take 60 seconds to see where everything lives.",
    },
    {
      anchor: ANCHORS.dashboard.kpiCards,
      route: LANDLORD_ROUTES.dashboard,
      title: "Your numbers at a glance",
      body: "These cards summarise your portfolio. They'll be zeros right now — by the end of this setup they'll be alive.",
    },
    {
      anchor: ANCHORS.sidebar.properties,
      route: LANDLORD_ROUTES.dashboard,
      title: "Properties & Units",
      body: "Everything starts here: you create properties, then units inside them, then place tenants in units.",
      mobileBody: "Open the ☰ menu and tap Properties. Everything starts here: you create properties, then units inside them, then place tenants in units.",
    },
    {
      anchor: ANCHORS.sidebar.invoices,
      route: LANDLORD_ROUTES.dashboard,
      title: "Invoices & Payments",
      body: "Each month you invoice tenants for rent and utilities, and record what they pay. Sahil Pay tracks every shilling per tenant, per line item.",
      mobileBody: "Open the ☰ menu and tap Invoices. Each month you invoice tenants for rent and utilities, and record what they pay. Sahil Pay tracks every shilling per tenant, per line item.",
    },
    {
      anchor: ANCHORS.sidebar.communications,
      route: LANDLORD_ROUTES.dashboard,
      title: "Talk to your tenants",
      body: "Send SMS and in-app messages — payment reminders, notices, receipts. We'll cover exactly how SMS works (and what it costs) in this setup.",
      mobileBody: "Open the ☰ menu and tap Communications. Send SMS and in-app messages — payment reminders, notices, receipts. We'll cover exactly how SMS works (and what it costs) in this setup.",
    },
    {
      anchor: ANCHORS.sidebar.tutorials,
      route: LANDLORD_ROUTES.dashboard,
      title: "Help is always here",
      body: "Every tutorial in this setup lives in Help & Tutorials, so you can re-run any of them whenever you need a refresher.",
      mobileBody: "Open the ☰ menu and tap Help & Tutorials. Every tutorial in this setup lives there, so you can re-run any of them whenever you need a refresher.",
    },
  ],
};
