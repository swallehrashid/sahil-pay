import { Smartphone, Link2, Search, Info } from "lucide-react";
import { LANDLORD_ROUTES } from "@/config/routePaths";

export default {
  id: "payments-and-mpesa",
  title: "Getting paid via M-Pesa",
  icon: Smartphone,
  duration: "~2 min",
  section: "payments",
  mode: "explainer",
  hubOnly: true,
  slides: [
    {
      icon: Smartphone,
      title: "Two phases",
      body: "Every landlord starts in manual mode: tenants pay you the way they always have, and you record it in Sahil Pay. Nothing about how you receive money changes.",
    },
    {
      icon: Link2,
      title: "Connecting M-Pesa",
      body: "When you're ready, contact the Sahil Pay team to connect your paybill or till. Once connected, every tenant payment is captured and recorded automatically, the second it lands — correct tenant, correct allocation, receipt available immediately. No more evening data entry.",
    },
    {
      icon: Search,
      title: "Checking a payment",
      body: "Tenant swears they paid but you can't see it? Settings → M-Pesa Status lets you check any M-Pesa reference against your shortcode and see instantly whether it was recorded.",
    },
    {
      icon: Info,
      title: "Also worth knowing",
      body: "You can also import bank statements (Payments → bank statement review) and, on Android, the Sahil Pay Co-pilot app can forward payment SMS automatically. Both are optional extras — manual recording always works.",
    },
  ],
  cta: { label: "Open M-Pesa Status", route: LANDLORD_ROUTES.settings.mpesa },
};
