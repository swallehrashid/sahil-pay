import { Building2 } from "lucide-react";
import { ANCHORS } from "../anchors";
import { LANDLORD_ROUTES } from "@/config/routePaths";

export default {
  id: "create-property",
  title: "Create a property",
  icon: Building2,
  duration: "~2 min",
  section: "setup",
  mode: "tour",
  steps: [
    {
      anchor: ANCHORS.sidebar.properties,
      route: LANDLORD_ROUTES.dashboard,
      title: "Open Properties",
      body: "Click Properties in the sidebar.",
      mobileBody: "Open the ☰ menu and tap Properties.",
      advanceOn: { event: "click" },
    },
    {
      anchor: ANCHORS.properties.addButton,
      route: LANDLORD_ROUTES.properties,
      title: "Add your property",
      body: "Click here to create your first property. A property is a building or plot — units and tenants will live inside it.",
      advanceOn: { event: "click" },
    },
    {
      anchor: ANCHORS.properties.form,
      route: LANDLORD_ROUTES.properties,
      title: "Fill in the details",
      body: "Give the property a name your tenants would recognise (e.g. \"Mombasa Heights\"), plus its location details. You can edit any of this later.",
    },
    {
      anchor: ANCHORS.properties.saveButton,
      route: LANDLORD_ROUTES.properties,
      title: "Save it",
      body: "Click save. That's it — your first property exists. Next we'll add the units inside it.",
    },
  ],
};
