import { BarChart3 } from "lucide-react";
import { ANCHORS } from "../anchors";
import { LANDLORD_ROUTES } from "@/config/routePaths";

export default {
  id: "reports",
  title: "Your reports",
  icon: BarChart3,
  duration: "~2 min",
  section: "reports",
  mode: "tour",
  steps: [
    {
      anchor: ANCHORS.reports.list,
      route: LANDLORD_ROUTES.reportsStatements,
      title: "Everything, on paper",
      body: "Every report SahilPay produces lives here — tenant statements, payment reports, arrears, income by category and more. All of them respect your charge categories, so the numbers match what you bill.",
    },
    {
      anchor: null,
      route: LANDLORD_ROUTES.reportsStatements,
      title: "The one to remember",
      body: "The tenant statement is the report you'll use most: a full money history for one tenant — every invoice, payment and balance. When a tenant disputes a balance, you send this and the conversation ends.",
    },
    {
      anchor: null,
      route: LANDLORD_ROUTES.reportsInsights,
      title: "Insights",
      body: "Charts and trends across your whole portfolio — collections over time, occupancy, arrears. Check it monthly; it tells you where to focus.",
    },
    {
      anchor: null,
      route: LANDLORD_ROUTES.reportsInsights,
      title: "Export anything",
      body: "Reports export to Excel and PDF — with your company logo once you've added it in Settings → General.",
    },
  ],
};
