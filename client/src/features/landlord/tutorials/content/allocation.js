import { ListOrdered, ArrowDownWideNarrow, SplitSquareVertical, ShieldCheck } from "lucide-react";
import { LANDLORD_ROUTES } from "@/config/routePaths";

export default {
  id: "allocation",
  title: "How payment allocation works",
  icon: ListOrdered,
  duration: "~2 min",
  section: "payments",
  // Permission module that gates this tutorial. Lives entirely in Settings, which is landlord-only.
  module: "settings",
  mode: "explainer",
  hubOnly: true,
  slides: [
    {
      icon: ListOrdered,
      title: "The problem it solves",
      body: "A tenant owes rent, water and a bit of last month — then pays KES 10,000. Which debt does it clear? Sahil Pay answers this the same way every time, using your priority order.",
    },
    {
      icon: ArrowDownWideNarrow,
      title: "Your priority order",
      body: "In Settings → General you rank every category-and-pocket (e.g. rent — balance before rent — current before water). Payments fill debts top-to-bottom in that order. Old arrears first is the common choice.",
    },
    {
      icon: SplitSquareVertical,
      title: "Partial & overpayment",
      body: "Partial payments fill as far down the list as the money reaches. Overpayments become credit, which is used automatically against the tenant's next invoice.",
    },
    {
      icon: ShieldCheck,
      title: "You're always in control",
      body: "Every allocation is visible line-by-line on the payment, and your reports break income down by exactly these categories.",
    },
  ],
  cta: { label: "Open allocation settings", route: LANDLORD_ROUTES.settings.general },
};
