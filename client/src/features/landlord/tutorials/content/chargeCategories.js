import { FolderTree, Layers, HelpCircle, RotateCw } from "lucide-react";
import { ANCHORS } from "../anchors";
import { LANDLORD_ROUTES } from "@/config/routePaths";

export default {
  id: "charge-categories",
  title: "Charge categories: how billing is organised",
  icon: FolderTree,
  duration: "~3 min",
  section: "billing",
  // Permission module that gates this tutorial. Charge categories are what invoice lines are built from.
  module: "invoices",
  mode: "mixed",
  slides: [
    {
      icon: FolderTree,
      title: "Everything you charge is a category",
      body: "Rent. Water. Electricity. Garbage. Lease fees. In Sahil Pay each of these is a charge category. Categories come in two kinds: utility categories (metered/recurring services, managed on the Utilities page) and invoice categories (rent and other charges, managed on the Invoices page).",
    },
    {
      icon: Layers,
      title: "Every category has three pockets",
      body: "",
      bullets: [
        "Current — this month's charge.",
        "Balance — arrears carried over from previous months.",
        "Deposit — refundable money you hold; it never mixes with rent and never counts as income.",
      ],
    },
    {
      icon: HelpCircle,
      title: "Why this matters",
      body: "Every invoice line, payment allocation and report is organised by category + pocket. When a tenant asks \"what exactly do I owe?\", you can answer to the shilling: \"KES 12,000 current rent, KES 3,500 water balance.\"",
    },
    {
      icon: RotateCw,
      title: "Month-end rollover",
      body: "Anything unpaid at month-end automatically rolls from current into balance — nothing is ever lost or forgotten. Deposits never roll; they just sit safely until refund day.",
    },
  ],
  steps: [
    {
      anchor: ANCHORS.invoices.categoriesButton,
      route: LANDLORD_ROUTES.invoices,
      title: "Invoice categories live here",
      body: "This is where you create and edit your invoice categories (rent is usually first).",
    },
    {
      anchor: ANCHORS.utilities.categoriesButton,
      route: LANDLORD_ROUTES.utilities,
      title: "Utility categories live here",
      body: "And utility categories live here. Set up the ones you actually bill — water and electricity are the usual starters.",
    },
  ],
};
