import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Download, Wallet } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import StatusBadge from "@/components/ui/StatusBadge";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { downloadFile } from "@/utils/downloadFile";
import { AFFILIATE_ROUTES } from "@/config/routePaths";
import { useGetAffiliateDashboardQuery } from "./affiliateApiSlice";
import { useGetAffiliateWithdrawalsQuery, useRequestAffiliateWithdrawalMutation } from "./affiliateApiSlice";

export default function AffiliateWithdrawals() {
  const { data: dashboard } = useGetAffiliateDashboardQuery();
  const { data, isLoading } = useGetAffiliateWithdrawalsQuery();
  const [requestWithdrawal, { isLoading: isRequesting }] = useRequestAffiliateWithdrawalMutation();
  const [amount, setAmount] = useState("");

  const affiliate = dashboard?.affiliate;
  const balance = Number(data?.balance ?? 0);
  const cfg = data?.config;
  const profileIncomplete = !affiliate?.mpesa_number || !affiliate?.national_id;
  const hasOpenWithdrawal = (data?.withdrawals ?? []).some((w) => ["requested", "processing"].includes(w.status));

  const preview = useMemo(() => {
    const gross = Number(amount);
    if (!cfg || !gross || gross <= 0) return null;
    const whtRate = Number(cfg.wht_rate);
    const wht = Math.round(gross * (whtRate / 100) * 100) / 100;
    const fee = cfg.fee_type === "flat" ? Number(cfg.fee_value) : Math.round(gross * (Number(cfg.fee_value) / 100) * 100) / 100;
    const net = gross - wht - fee;
    return { gross, wht, fee, net, whtRate, feeLabel: cfg.fee_type === "flat" ? formatCurrency(cfg.fee_value) : `${cfg.fee_value}%` };
  }, [amount, cfg]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      await requestWithdrawal({ amount }).unwrap();
      toast("Withdrawal requested.", { type: "success" });
      setAmount("");
    } catch (err) {
      toast(err?.data?.error || "Could not request withdrawal.", { type: "error" });
    }
  };

  const downloadReceipt = async (w) => {
    try {
      await downloadFile(`/affiliate/withdrawals/${w.id}/receipt`, { filename: `${w.receipt_number}.pdf`, format: "pdf" });
    } catch {
      toast("Could not download receipt.", { type: "error" });
    }
  };

  const columns = [
    { key: "created_at", header: "Requested", render: (r) => formatDate(r.created_at) },
    { key: "gross_amount", header: "Gross", render: (r) => formatCurrency(r.gross_amount) },
    { key: "wht_amount", header: "WHT", render: (r) => formatCurrency(r.wht_amount) },
    { key: "fee_amount", header: "Fee", render: (r) => formatCurrency(r.fee_amount) },
    { key: "net_amount", header: "Net", render: (r) => formatCurrency(r.net_amount) },
    { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
    {
      key: "receipt",
      header: "Receipt",
      render: (r) =>
        r.status === "paid" ? (
          <Button variant="ghost" size="sm" leftIcon={<Download className="h-3.5 w-3.5" />} onClick={() => downloadReceipt(r)}>
            {r.receipt_number}
          </Button>
        ) : (
          "—"
        ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Withdrawals" subtitle="Request a payout and download your KRA-compliant receipts" />

      {profileIncomplete && (
        <div className="glass border border-amber-500/30 bg-amber-500/10 p-5 text-sm text-amber-200">
          Add your M-Pesa number and national ID on your{" "}
          <Link to={AFFILIATE_ROUTES.profile} className="underline">
            profile
          </Link>{" "}
          before requesting a withdrawal.
        </div>
      )}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <SummaryCard label="Available balance" value={formatCurrency(balance)} icon={<Wallet className="h-5 w-5" />} accent="secondary" />

        <form onSubmit={handleSubmit} className="glass space-y-4 p-6 lg:col-span-2">
          <h3 className="text-base font-medium text-white">Request a withdrawal</h3>
          <Input
            label={`Amount (min ${cfg ? formatCurrency(cfg.min_withdrawal) : "—"})`}
            type="number"
            step="0.01"
            min="0"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            disabled={profileIncomplete || hasOpenWithdrawal}
            required
          />
          {preview && (
            <div className="rounded-xl bg-white/5 p-4 text-sm">
              <Row label="Gross" value={formatCurrency(preview.gross)} />
              <Row label={`Withholding tax (${preview.whtRate}%)`} value={`-${formatCurrency(preview.wht)}`} />
              <Row label={`Platform fee (${preview.feeLabel})`} value={`-${formatCurrency(preview.fee)}`} />
              <Row label="Net you'll receive" value={formatCurrency(preview.net)} bold />
            </div>
          )}
          <div className="flex justify-end">
            <Button type="submit" isLoading={isRequesting} disabled={profileIncomplete || hasOpenWithdrawal}>
              {hasOpenWithdrawal ? "Withdrawal already in progress" : "Request withdrawal"}
            </Button>
          </div>
        </form>
      </div>

      <div className="glass p-6">
        <h3 className="mb-4 text-sm font-medium text-white/70">Withdrawal history</h3>
        <ResponsiveTable
          columns={columns}
          rows={data?.withdrawals ?? []}
          isLoading={isLoading}
          emptyState={<div className="py-10 text-center text-sm text-white/50">No withdrawals yet.</div>}
        />
      </div>
    </div>
  );
}

function Row({ label, value, bold }) {
  return (
    <div className={`flex items-center justify-between py-1 ${bold ? "mt-1 border-t border-white/10 pt-2 font-semibold text-white" : "text-white/60"}`}>
      <span>{label}</span>
      <span>{value}</span>
    </div>
  );
}
