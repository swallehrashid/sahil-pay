import { Link } from "react-router-dom";
import { FilePlus, Users, DoorOpen, Gauge, UserPlus, ArrowRightLeft } from "lucide-react";
import { LANDLORD_ROUTES } from "@/config/routePaths";

const ACTIONS = [
  { label: "Add invoice", icon: FilePlus, to: LANDLORD_ROUTES.invoices },
  { label: "Add tenant", icon: Users, to: LANDLORD_ROUTES.tenants },
  { label: "Shift tenant", icon: ArrowRightLeft, to: LANDLORD_ROUTES.tenants },
  { label: "Add unit", icon: DoorOpen, to: LANDLORD_ROUTES.units },
  { label: "Add utility reading", icon: Gauge, to: LANDLORD_ROUTES.utilities },
  { label: "Add team member", icon: UserPlus, to: LANDLORD_ROUTES.settings.team },
];

// §4.1 quick-actions tab.
export default function QuickActions() {
  return (
    <div className="glass animate-fade-in-up p-6">
      <h3 className="mb-4 text-base font-medium text-white">Quick actions</h3>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {ACTIONS.map((action, index) => (
          <Link
            key={action.label}
            to={action.to}
            style={{ animationDelay: `${index * 50}ms` }}
            className="card-hover animate-fade-in-up flex flex-col items-center gap-2 rounded-xl bg-white/5 px-3 py-4 text-center text-xs text-white/70 transition-colors hover:text-white"
          >
            <action.icon className="h-5 w-5 text-secondary" />
            {action.label}
          </Link>
        ))}
      </div>
    </div>
  );
}
