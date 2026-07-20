import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { Ban, RotateCcw, Save } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import StatusBadge from "@/components/ui/StatusBadge";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Spinner from "@/components/ui/Spinner";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import { toast } from "@/components/ui/Toast";
import { formatCurrency } from "@/utils/currencyFormatter";
import { formatDate } from "@/utils/dateFormatter";
import { ADMIN_ROUTES } from "@/config/routePaths";
import {
  useGetAdminAffiliateDetailQuery, useUpdateAffiliateMutation, useSuspendAffiliateMutation,
  useReactivateAffiliateMutation, useUpdateAffiliateReferralMutation, useVoidAffiliateReferralMutation,
} from "./adminAffiliateApiSlice";

export default function AdminAffiliateDetail() {
  const { id } = useParams();
  const { data, isLoading } = useGetAdminAffiliateDetailQuery(id);
  const [updateAffiliate, { isLoading: isSavingTerms }] = useUpdateAffiliateMutation();
  const [suspend] = useSuspendAffiliateMutation();
  const [reactivate] = useReactivateAffiliateMutation();
  const [confirmSuspend, setConfirmSuspend] = useState(false);

  const [termsForm, setTermsForm] = useState(null);
  const affiliate = data?.affiliate;

  if (isLoading || !affiliate) return <Spinner className="mx-auto my-10" />;

  const terms = termsForm ?? {
    commission_rate_override: affiliate.commission_rate_override ?? "",
    commission_months_override: affiliate.commission_months_override ?? "",
    notes: affiliate.notes ?? "",
  };

  const saveTerms = async (e) => {
    e.preventDefault();
    try {
      await updateAffiliate({
        id: affiliate.id,
        commission_rate_override: terms.commission_rate_override === "" ? null : terms.commission_rate_override,
        commission_months_override: terms.commission_months_override === "" ? null : terms.commission_months_override,
        notes: terms.notes,
      }).unwrap();
      toast("Terms updated (applies to future referrals only).", { type: "success" });
      setTermsForm(null);
    } catch {
      toast("Could not update terms.", { type: "error" });
    }
  };

  const handleSuspendToggle = async () => {
    try {
      if (affiliate.status === "suspended") {
        await reactivate(affiliate.id).unwrap();
        toast("Affiliate reactivated.", { type: "success" });
      } else {
        await suspend(affiliate.id).unwrap();
        toast("Affiliate suspended.", { type: "success" });
      }
    } catch {
      toast("Could not update affiliate status.", { type: "error" });
    } finally {
      setConfirmSuspend(false);
    }
  };

  const commissionColumns = [
    { key: "created_at", header: "Date", render: (r) => formatDate(r.created_at) },
    { key: "amount", header: "Amount", render: (r) => formatCurrency(r.amount) },
    { key: "rate_applied", header: "Rate", render: (r) => `${r.rate_applied}%` },
    { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
  ];

  const withdrawalColumns = [
    { key: "created_at", header: "Requested", render: (r) => formatDate(r.created_at) },
    { key: "gross_amount", header: "Gross", render: (r) => formatCurrency(r.gross_amount) },
    { key: "net_amount", header: "Net", render: (r) => formatCurrency(r.net_amount) },
    { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
    { key: "receipt_number", header: "Receipt", render: (r) => r.receipt_number ?? "—" },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title={affiliate.full_name}
        subtitle={`${affiliate.referral_code} — ${affiliate.status}`}
        breadcrumbs={[
          { label: "Admin", to: ADMIN_ROUTES.dashboard },
          { label: "Affiliates", to: ADMIN_ROUTES.affiliates },
          { label: affiliate.full_name },
        ]}
        actions={
          <Button
            variant={affiliate.status === "suspended" ? "primary" : "danger"}
            leftIcon={affiliate.status === "suspended" ? <RotateCcw className="h-4 w-4" /> : <Ban className="h-4 w-4" />}
            onClick={() => setConfirmSuspend(true)}
            disabled={affiliate.status === "pending" || affiliate.status === "rejected"}
          >
            {affiliate.status === "suspended" ? "Reactivate" : "Suspend"}
          </Button>
        }
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard label="Balance" value={formatCurrency(data.summary?.balance)} accent="secondary" />
        <SummaryCard label="Lifetime earned" value={formatCurrency(data.summary?.lifetime_earned)} />
        <SummaryCard label="Total withdrawn" value={formatCurrency(data.summary?.total_withdrawn)} />
        <SummaryCard label="Referrals" value={data.summary?.referral_counts?.total ?? 0} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="glass space-y-2 p-6">
          <h3 className="text-sm font-medium text-white/70">Contact & payout</h3>
          <Row label="Email" value={affiliate.user_id ? "See user record" : "—"} />
          <Row label="Phone" value={affiliate.phone} />
          <Row label="M-Pesa number" value={affiliate.mpesa_number ?? "Not set"} />
          <Row label="National ID" value={affiliate.national_id ?? "Not set"} />
          <Row label="KRA PIN" value={affiliate.kra_pin ?? "Not set"} />
        </div>

        <form onSubmit={saveTerms} className="glass space-y-4 p-6">
          <h3 className="text-sm font-medium text-white/70">Commission terms (future referrals only)</h3>
          <div className="grid grid-cols-2 gap-4">
            <Input
              label="Rate override (%)"
              type="number"
              step="0.01"
              value={terms.commission_rate_override}
              onChange={(e) => setTermsForm({ ...terms, commission_rate_override: e.target.value })}
              placeholder="Program default"
            />
            <Input
              label="Months override"
              type="number"
              value={terms.commission_months_override}
              onChange={(e) => setTermsForm({ ...terms, commission_months_override: e.target.value })}
              placeholder="Program default"
            />
          </div>
          <Input
            label="Admin notes"
            value={terms.notes}
            onChange={(e) => setTermsForm({ ...terms, notes: e.target.value })}
          />
          <div className="flex justify-end">
            <Button type="submit" size="sm" leftIcon={<Save className="h-3.5 w-3.5" />} isLoading={isSavingTerms}>
              Save terms
            </Button>
          </div>
        </form>
      </div>

      <div className="glass p-6">
        <h3 className="mb-4 text-sm font-medium text-white/70">Referrals</h3>
        <ReferralsTable rows={data.referrals ?? []} />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="glass p-6">
          <h3 className="mb-4 text-sm font-medium text-white/70">Recent commissions</h3>
          <ResponsiveTable columns={commissionColumns} rows={data.commissions ?? []} emptyState={<Empty text="No commissions yet." />} />
        </div>
        <div className="glass p-6">
          <h3 className="mb-4 text-sm font-medium text-white/70">Withdrawals</h3>
          <ResponsiveTable columns={withdrawalColumns} rows={data.withdrawals ?? []} emptyState={<Empty text="No withdrawals yet." />} />
        </div>
      </div>

      <ConfirmDialog
        isOpen={confirmSuspend}
        onClose={() => setConfirmSuspend(false)}
        onConfirm={handleSuspendToggle}
        title={affiliate.status === "suspended" ? "Reactivate affiliate?" : "Suspend affiliate?"}
        description={
          affiliate.status === "suspended"
            ? "This affiliate's referral code will resume attributing new landlords."
            : "Their referral code stops attributing new landlords and withdrawals are blocked — but existing referrals keep earning normally."
        }
        confirmLabel={affiliate.status === "suspended" ? "Reactivate" : "Suspend"}
        isDangerous={affiliate.status !== "suspended"}
      />
    </div>
  );
}

function ReferralsTable({ rows }) {
  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState({ rate: "", months_total: "" });
  const [updateReferral, { isLoading }] = useUpdateAffiliateReferralMutation();
  const [voidReferral] = useVoidAffiliateReferralMutation();

  const startEdit = (r) => {
    setEditingId(r.id);
    setEditForm({ rate: r.rate, months_total: r.months_total });
  };

  const saveEdit = async () => {
    try {
      await updateReferral({ id: editingId, rate: editForm.rate, months_total: Number(editForm.months_total) }).unwrap();
      toast("Referral updated.", { type: "success" });
      setEditingId(null);
    } catch {
      toast("Could not update referral.", { type: "error" });
    }
  };

  const handleVoid = async (r) => {
    try {
      await voidReferral(r.id).unwrap();
      toast("Referral voided.", { type: "success" });
    } catch {
      toast("Could not void referral.", { type: "error" });
    }
  };

  const columns = [
    { key: "landlord_company_name", header: "Landlord", render: (r) => (
      <Link to={ADMIN_ROUTES.landlordDetailPath(r.landlord_id)} className="text-secondary hover:underline">
        {r.landlord_company_name ?? `#${r.landlord_id}`}
      </Link>
    ) },
    {
      key: "rate", header: "Rate", render: (r) =>
        editingId === r.id ? (
          <input
            type="number" step="0.01" value={editForm.rate}
            onChange={(e) => setEditForm((f) => ({ ...f, rate: e.target.value }))}
            className="glass-input w-20 py-1 text-sm"
          />
        ) : `${r.rate}%`,
    },
    {
      key: "months", header: "Months", render: (r) =>
        editingId === r.id ? (
          <input
            type="number" value={editForm.months_total}
            onChange={(e) => setEditForm((f) => ({ ...f, months_total: e.target.value }))}
            className="glass-input w-16 py-1 text-sm"
          />
        ) : `${r.months_used}/${r.months_total}`,
    },
    { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
    { key: "attributed_by", header: "Attributed via", render: (r) => r.attributed_by },
  ];

  return (
    <ResponsiveTable
      columns={columns}
      rows={rows}
      emptyState={<Empty text="No referrals yet." />}
      rowActions={(r) =>
        r.status === "void" ? null : editingId === r.id ? (
          <div className="flex justify-end gap-2">
            <Button size="sm" onClick={saveEdit} isLoading={isLoading}>Save</Button>
            <Button size="sm" variant="ghost" onClick={() => setEditingId(null)}>Cancel</Button>
          </div>
        ) : (
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={() => startEdit(r)}>Edit</Button>
            <Button size="sm" variant="danger" onClick={() => handleVoid(r)}>Void</Button>
          </div>
        )
      }
    />
  );
}

function Row({ label, value }) {
  return (
    <div className="flex items-center justify-between text-sm">
      <span className="text-white/50">{label}</span>
      <span className="text-white/80">{value}</span>
    </div>
  );
}

function Empty({ text }) {
  return <div className="py-8 text-center text-sm text-white/50">{text}</div>;
}
