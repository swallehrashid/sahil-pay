import { MessageSquare, Send, Tag, ListChecks, Bell } from "lucide-react";
import { ANCHORS } from "../anchors";
import { LANDLORD_ROUTES } from "@/config/routePaths";

export default {
  id: "communications",
  title: "Messaging your tenants: SMS & in-app",
  icon: MessageSquare,
  duration: "~4 min",
  section: "communication",
  mode: "mixed",
  slides: [
    {
      icon: MessageSquare,
      title: "Two channels, two costs",
      body: "SahilPay gives you two ways to reach tenants: in-app notifications — free, unlimited, delivered inside the tenant's portal — and SMS — delivered to their phone even without internet, paid per message from your SMS credits.",
    },
    {
      icon: Send,
      title: "How SMS sending works today",
      body: "Out of the box, your SMS go out under the sender name SahilPay. Tenants see \"SahilPay\" as the sender. You don't need to set up anything — top up SMS credits (Settings → Billing) and send. Your credit balance is always visible, and every sent message is logged.",
    },
    {
      icon: Tag,
      title: "Your own sender name (optional)",
      body: "Want messages to arrive as your brand instead of SahilPay? Register your own sender ID with Africa's Talking, then connect it under Settings → SMS Provider. From that moment your SMS carry your name and are sent through your own account — SahilPay just charges a small per-SMS service fee (often cheaper than the shared sender, too). Until you do this, the SahilPay sender works fine; most landlords start there.",
    },
    {
      icon: ListChecks,
      title: "What to send, when",
      body: "",
      bullets: [
        "Invoice reminders when you bill.",
        "Payment receipts / thank-yous.",
        "Balance reminders before month-end — templates for these are built in.",
        "Notices (water shutoffs, inspections) — in-app is free and perfect for these.",
      ],
    },
    {
      icon: Bell,
      title: "In-app notifications",
      body: "Send from the Notifications page in your sidebar. Free, instant, and the tenant sees it next time they open their portal. Rule of thumb: urgent or money-related → SMS; everything else → in-app first.",
    },
  ],
  steps: [
    {
      anchor: ANCHORS.communications.composeButton,
      route: LANDLORD_ROUTES.communications,
      title: "Compose an SMS",
      body: "Compose an SMS here: pick the tenant, write or pick a template, send.",
    },
    {
      anchor: ANCHORS.communications.templatesTab,
      route: LANDLORD_ROUTES.communications,
      title: "Templates save retyping",
      body: "Balance reminders and invoice reminders are ready to personalise.",
    },
    {
      anchor: ANCHORS.communications.log,
      route: LANDLORD_ROUTES.communications,
      title: "Every message, logged",
      body: "Every message ever sent, with delivery status. If one fails, resend it from here.",
    },
    {
      anchor: null,
      route: LANDLORD_ROUTES.notificationsSend,
      title: "Free in-app notifications",
      body: "And this is where free in-app notifications are sent from.",
    },
  ],
};
