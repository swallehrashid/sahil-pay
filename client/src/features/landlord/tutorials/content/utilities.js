import { Droplets } from "lucide-react";
import { ANCHORS } from "../anchors";
import { LANDLORD_ROUTES } from "@/config/routePaths";

export default {
  id: "record-utilities",
  title: "Record meter readings and send them for billing",
  icon: Droplets,
  duration: "~3 min",
  section: "billing",
  // Anyone who can edit utilities — typically the caretaker on the ground.
  module: "utilities",
  mode: "tour",
  steps: [
    {
      anchor: ANCHORS.sidebar.utilities,
      route: LANDLORD_ROUTES.dashboard,
      title: "Open Utilities",
      body: "Click Utilities in the sidebar.",
      mobileBody: "Open the ☰ menu and tap Utilities.",
      advanceOn: { event: "click" },
    },
    {
      anchor: ANCHORS.utilities.recordButton,
      route: LANDLORD_ROUTES.utilities,
      title: "One reading at a time",
      body: "Record reading is for a single meter: pick the property, the unit, the utility and type the current reading.",
    },
    {
      anchor: ANCHORS.utilities.bulkButton,
      route: LANDLORD_ROUTES.utilities,
      title: "A whole block at once",
      body: "Bulk upload lists every unit in a property so you can type all the month's readings on one screen. At the end choose \"Queue for next month's invoice\" (or \"Submit for review\").",
    },
    {
      anchor: ANCHORS.utilities.queueButton,
      route: LANDLORD_ROUTES.utilities,
      title: "Send them for billing",
      body: "Readings you have already saved can be sent from here for a property and month. If you cannot bill, they go to the office for review first — nothing reaches a tenant until someone approves it.",
    },
    {
      anchor: null,
      route: LANDLORD_ROUTES.utilities,
      title: "Follow each reading",
      body: "The Status column shows where every reading is: Waiting for review, Approved · next invoice, or Invoiced with the invoice number.",
    },
  ],
};
