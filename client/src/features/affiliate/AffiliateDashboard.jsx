import { Link } from "react-router-dom";
import { Wallet, TrendingUp, Users, Copy, CheckCircle2, Banknote } from "lucide-react";
import { useState } from "react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { formatCurrency } from "@/utils/currencyFormatter";
import { AFFILIATE_ROUTES } from "@/config/routePaths";
import { useGetAffiliateDashboardQuery } from "./affiliateApiSlice";

export default function AffiliateDashboard() {
  const { data, isLoading } = useGetAffiliateDashboardQuery();
  const [copied, setCopied] = useState(false);

  const affiliate = data?.affiliate;
  const summary = data?.summary;
  const balance = Number(summary?.balance ?? 0);
  const isPending = affiliate?.status === "pending";
  const isSuspended = affiliate?.status === "suspended";
  const isRejected = affiliate?.status === "rejected";

  const shareLink = affiliate?.referral_code
    ? `${window.location.origin}/register?ref=${affiliate.referral_code}`
    : "";

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(shareLink);
      setCopied(true);
      toast("Referral link copied.", { type: "success" });
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast("Could not copy link.", { type: "error" });
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader title="Affiliate dashboard" subtitle="Your referrals, earnings, and payout status at a glance" />

      {isPending && (
        <div className="glass border border-amber-500/30 bg-amber-500/10 p-5 text-sm text-amber-200">
          Your account is awaiting admin approval. Your referral code will activate once approved —
          you'll be notified.
        </div>
      )}
      {isRejected && (
        <div className="glass border border-secondary/30 bg-secondary/10 p-5 text-sm text-secondary-100">
          Your affiliate application was not approved. Contact SahilPay support for details.
        </div>
      )}
      {isSuspended && (
        <div className="glass border border-secondary/30 bg-secondary/10 p-5 text-sm text-secondary-100">
          Your account is suspended — withdrawals are blocked, but any referrals you've already made
          keep earning normally.
        </div>
      )}

      {isLoading ? (
        <SkeletonStatCards count={5} />
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
          <SummaryCard
            label="Available balance"
            value={formatCurrency(balance)}
            icon={<Wallet className="h-5 w-5" />}
            accent="secondary"
            trend={balance < 0 ? { label: "Negative — a referred payment was reversed; future commissions offset this.", positive: false } : undefined}
          />
          <SummaryCard label="Lifetime earned" value={formatCurrency(summary?.lifetime_earned)} icon={<TrendingUp className="h-5 w-5" />} />
          <SummaryCard label="Total withdrawn" value={formatCurrency(summary?.total_withdrawn)} icon={<Banknote className="h-5 w-5" />} accent="third" />
          <SummaryCard label="Projected monthly" value={formatCurrency(summary?.projected_monthly)} icon={<TrendingUp className="h-5 w-5" />} accent="secondary" />
          <SummaryCard label="Total referrals" value={summary?.referral_counts?.total ?? 0} icon={<Users className="h-5 w-5" />} />
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="glass p-6 lg:col-span-2">
          <h3 className="text-base font-medium text-white">Your referral link</h3>
          <p className="mt-1 text-sm text-white/50">
            Share this link, or give landlords your code <strong className="text-white/80">{affiliate?.referral_code}</strong> to
            enter at registration.
          </p>
          <div className="mt-4 flex flex-col gap-2 sm:flex-row">
            <input
              readOnly
              value={shareLink}
              className="glass-input w-full flex-1 text-sm text-white/70"
              onFocus={(e) => e.target.select()}
            />
            <Button variant="subtle" onClick={copyLink} leftIcon={copied ? <CheckCircle2 className="h-4 w-4" /> : <Copy className="h-4 w-4" />}>
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>
        </div>

        <div className="glass space-y-3 p-6">
          <h3 className="text-base font-medium text-white">Referral status</h3>
          <StatRow label="Active &amp; paying" value={summary?.referral_counts?.active_paying ?? 0} />
          <StatRow label="Completed (4 months)" value={summary?.referral_counts?.completed ?? 0} />
          <StatRow label="Not yet paying" value={summary?.referral_counts?.not_yet_paying ?? 0} />
          <Link to={AFFILIATE_ROUTES.referrals} className="mt-2 inline-block text-sm text-secondary hover:underline">
            View all referrals →
          </Link>
        </div>
      </div>

      {summary?.has_pending_withdrawal && (
        <div className="glass border border-third/30 bg-third/10 p-5 text-sm text-third-100">
          You have a withdrawal request in progress.{" "}
          <Link to={AFFILIATE_ROUTES.withdrawals} className="underline">
            View status
          </Link>
        </div>
      )}
    </div>
  );
}

function StatRow({ label, value }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-white/50">{label}</span>
      <span className="font-medium text-white">{value}</span>
    </div>
  );
}
