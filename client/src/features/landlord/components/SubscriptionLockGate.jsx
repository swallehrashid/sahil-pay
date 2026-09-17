import { Link, useLocation } from "react-router-dom";
import { Lock, Smartphone, LogOut } from "lucide-react";
import Button from "@/components/ui/Button";
import { useAuth } from "@/hooks/useAuth";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { LANDLORD_ROUTES } from "@/config/routePaths";
import { useGetBillingAccessQuery } from "@/features/landlord/settings/billingApiSlice";

/**
 * Wraps a portal's pages. When the account is locked for an unpaid subscription
 * balance, every page except Billing is replaced with one clear explanation and
 * a way to pay. The server enforces the same rule (402 subscription_locked), so
 * this is the honest face of it rather than a screen full of failed requests.
 *
 * Tenants, rent collection and receipts are unaffected — only the office portal
 * is paused.
 */
export default function SubscriptionLockGate({ children, portal = "landlord" }) {
  const { pathname } = useLocation();
  const { logout, user } = useAuth();
  const { data: access } = useGetBillingAccessQuery(undefined, { pollingInterval: 120000 });

  const onBilling = pathname.startsWith(LANDLORD_ROUTES.settings.billing);
  if (!access?.locked || onBilling || user?.role === "system_admin") return children;

  const isOwner = portal === "landlord";
  return (
    <div className="flex min-h-[70vh] items-center justify-center" data-testid="subscription-locked">
      <div className="glass w-full max-w-lg space-y-5 p-6 text-center sm:p-8">
        <span className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-red-500/20">
          <Lock className="h-8 w-8 text-red-200" />
        </span>
        <div>
          <h1 className="text-2xl font-light text-white">Your account is paused</h1>
          <p className="mt-2 text-sm text-white/65">
            {access.reason === "suspended"
              ? "This account has been suspended. Please contact Sahil Pay support."
              : <>There is an unpaid subscription balance of <strong className="text-white">{formatCurrency(access.balance)}</strong>
                {access.balance_due_since ? <> owing since {formatDate(access.balance_due_since)}</> : null}.</>}
          </p>
        </div>
        <ul className="space-y-1.5 rounded-xl bg-white/5 p-4 text-left text-sm text-white/70">
          <li>• Pay any amount by M-Pesa — the account opens as soon as the balance is cleared.</li>
          <li>• Your tenants can still pay rent and get receipts while it is paused.</li>
          <li>• Need more time? Call Sahil Pay on 0114 129 809.</li>
        </ul>
        {isOwner ? (
          <Link to={LANDLORD_ROUTES.settings.billing} className="block">
            <Button className="w-full" leftIcon={<Smartphone className="h-4 w-4" />}>Go to Billing and pay</Button>
          </Link>
        ) : (
          <p className="text-sm text-amber-200">Please ask the account owner to pay the balance in Settings → Billing.</p>
        )}
        <button onClick={logout} className="inline-flex items-center gap-1.5 text-sm text-white/50 hover:text-white">
          <LogOut className="h-4 w-4" /> Log out
        </button>
      </div>
    </div>
  );
}
