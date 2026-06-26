import { Link } from "react-router-dom";
import { CreditCard, MessageSquarePlus } from "lucide-react";
import Button from "@/components/ui/Button";
import { LANDLORD_ROUTES } from "@/config/routePaths";

// §4.1 pay-subscription + buy-SMS shortcuts.
export default function SubscriptionShortcut() {
  return (
    <div className="glass animate-fade-in-up space-y-3 p-6">
      <h3 className="text-base font-medium text-white">Billing</h3>
      <Link to={LANDLORD_ROUTES.settings.billing}>
        <Button variant="ghost" size="sm" className="w-full justify-start" leftIcon={<CreditCard className="h-4 w-4" />}>
          Pay subscription
        </Button>
      </Link>
      <Link to={LANDLORD_ROUTES.settings.billing}>
        <Button variant="ghost" size="sm" className="w-full justify-start" leftIcon={<MessageSquarePlus className="h-4 w-4" />}>
          Buy SMS
        </Button>
      </Link>
    </div>
  );
}
