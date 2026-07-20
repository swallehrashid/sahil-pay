import { DoorOpen } from "lucide-react";
import { ANCHORS } from "../anchors";
import { LANDLORD_ROUTES } from "@/config/routePaths";

export default {
  id: "add-units",
  title: "Add units to a property",
  icon: DoorOpen,
  duration: "~2 min",
  section: "setup",
  mode: "tour",
  prerequisite: { count: "properties", tutorialId: "create-property" },
  steps: [
    {
      anchor: ANCHORS.sidebar.units,
      route: LANDLORD_ROUTES.dashboard,
      title: "Open Units",
      body: "Click Units in the sidebar.",
      mobileBody: "Open the ☰ menu and tap Units.",
      advanceOn: { event: "click" },
    },
    {
      anchor: ANCHORS.units.addButton,
      route: LANDLORD_ROUTES.units,
      title: "Add a unit",
      body: "Click here to add a unit.",
      advanceOn: { event: "click" },
    },
    {
      anchor: ANCHORS.units.form,
      route: LANDLORD_ROUTES.units,
      title: "Fill in the unit",
      body: "Pick the property, then give the unit its door label (e.g. \"A1\"), its monthly rent and its deposit. Rent set here is what invoices will bill each month.",
    },
    {
      anchor: ANCHORS.units.propertySelect,
      route: LANDLORD_ROUTES.units,
      title: "One property, many units",
      body: "Every unit belongs to a property — if you manage several, this is how everything stays organised.",
    },
    {
      anchor: ANCHORS.units.saveButton,
      route: LANDLORD_ROUTES.units,
      title: "Save it",
      body: "Save the unit — it's ready to hold a tenant.",
    },
    {
      anchor: null,
      route: LANDLORD_ROUTES.units,
      title: "Repeat for each unit",
      body: "Most landlords add all their units now while they're at it — you can always come back and add more later.",
    },
  ],
};
