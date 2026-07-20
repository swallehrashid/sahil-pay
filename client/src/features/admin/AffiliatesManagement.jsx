import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Handshake, Wallet, UserPlus, Link2 } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import Tabs from "@/components/ui/Tabs";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import StatusBadge from "@/components/ui/StatusBadge";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import Input from "@/components/ui/Input";
import { toast } from "@/components/ui/Toast";
import Pagination from "@/components/ui/Pagination";
import { usePagination } from "@/hooks/usePagination";
import { formatCurrency } from "@/utils/currencyFormatter";
import { ADMIN_ROUTES } from "@/config/routePaths";
import {
  useGetAdminAffiliatesQuery, useApproveAffiliateMutation, useRejectAffiliateMutation,
  useAttributeAffiliateReferralMutation,
} from "./adminAffiliateApiSlice";
import { useGetAdminLandlordsQuery } from "./adminApiSlice";

const TABS = [
  { key: "", label: "All" },
  { key: "pending", label: "Pending approval" },
  { key: "active", label: "Active" },
  { key: "suspended", label: "Suspended" },
];

export default function AffiliatesManagement() {
  const navigate = useNavigate();
  const [status, setStatus] = useState("");
  const [attributeOpen, setAttributeOpen] = useState(false);
  const { page, perPage, setPage, setPerPage, params } = usePagination(25);

  const { data, isLoading } = useGetAdminAffiliatesQuery({ ...params, ...(status ? { status } : {}) });
  const [approve] = useApproveAffiliateMutation();
  const [reject] = useRejectAffiliateMutation();

  const handleApprove = async (a) => {
    try {
      await approve({ id: a.id }).unwrap();
      toast(`${a.full_name} approved.`, { type: "success" });
    } catch {
      toast("Could not approve affiliate.", { type: "error" });
    }
  };

  const handleReject = async (a) => {
    try {
      await reject({ id: a.id, reason: "Rejected by admin" }).unwrap();
      toast(`${a.full_name} rejected.`, { type: "success" });
    } catch {
      toast("Could not reject affiliate.", { type: "error" });
    }
  };

  const columns = [
    { key: "full_name", header: "Affiliate", render: (r) => r.full_name },
    { key: "referral_code", header: "Code", render: (r) => <span className="font-mono text-xs">{r.referral_code}</span> },
    { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
    { key: "referral_count", header: "Referrals", render: (r) => r.referral_count ?? 0 },
    { key: "balance", header: "Balance", render: (r) => formatCurrency(r.balance) },
    {
      key: "rate",
      header: "Rate",
      render: (r) => (r.commission_rate_override ? `${r.commission_rate_override}% (custom)` : "Default"),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Affiliates"
        subtitle="Approve, monitor and manage the affiliate referral program"
        breadcrumbs={[{ label: "Admin", to: ADMIN_ROUTES.dashboard }, { label: "Affiliates" }]}
        actions={
          <>
            <Button variant="ghost" onClick={() => navigate(ADMIN_ROUTES.affiliateWithdrawals)}>Withdrawal queue</Button>
            <Button variant="ghost" onClick={() => navigate(ADMIN_ROUTES.affiliateReports)}>Reports</Button>
            <Button variant="ghost" onClick={() => navigate(ADMIN_ROUTES.affiliateSettings)}>Settings</Button>
            <Button leftIcon={<Link2 className="h-4 w-4" />} onClick={() => setAttributeOpen(true)}>
              Attribute referral
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <SummaryCard
          label="Total outstanding liability"
          value={formatCurrency(data?.total_outstanding_liability)}
          icon={<Wallet className="h-5 w-5" />}
          accent="secondary"
        />
        <SummaryCard label="Total affiliates" value={data?.total ?? 0} icon={<Handshake className="h-5 w-5" />} />
        <SummaryCard
          label="Pending approval"
          value={(data?.affiliates ?? []).filter((a) => a.status === "pending").length}
          icon={<UserPlus className="h-5 w-5" />}
          accent="secondary"
        />
      </div>

      <Tabs tabs={TABS} activeKey={status} onChange={(k) => { setStatus(k); setPage(1); }} />

      <div className="glass p-6">
        <ResponsiveTable
          columns={columns}
          rows={data?.affiliates ?? []}
          isLoading={isLoading}
          onRowClick={(r) => navigate(ADMIN_ROUTES.affiliateDetailPath(r.id))}
          rowActions={(r) =>
            r.status === "pending" ? (
              <div className="flex justify-end gap-2">
                <Button size="sm" onClick={() => handleApprove(r)}>Approve</Button>
                <Button size="sm" variant="danger" onClick={() => handleReject(r)}>Reject</Button>
              </div>
            ) : null
          }
          emptyState={<div className="py-10 text-center text-sm text-white/50">No affiliates found.</div>}
        />
        <Pagination page={page} perPage={perPage} total={data?.total ?? 0} onPageChange={setPage} onPerPageChange={setPerPage} />
      </div>

      <AttributeReferralModal isOpen={attributeOpen} onClose={() => setAttributeOpen(false)} />
    </div>
  );
}

function AttributeReferralModal({ isOpen, onClose }) {
  const [search, setSearch] = useState("");
  const [landlordId, setLandlordId] = useState("");
  const [affiliateId, setAffiliateId] = useState("");
  const { data: landlordData } = useGetAdminLandlordsQuery({ search, per_page: 10 }, { skip: !isOpen });
  const { data: affiliateData } = useGetAdminAffiliatesQuery({ status: "active", per_page: 100 }, { skip: !isOpen });
  const [attribute, { isLoading }] = useAttributeAffiliateReferralMutation();

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!landlordId || !affiliateId) {
      toast("Select both a landlord and an affiliate.", { type: "error" });
      return;
    }
    try {
      await attribute({ landlord_id: Number(landlordId), affiliate_id: Number(affiliateId) }).unwrap();
      toast("Referral attributed.", { type: "success" });
      onClose();
      setLandlordId("");
      setAffiliateId("");
    } catch (err) {
      toast(err?.data?.error || "Could not attribute referral.", { type: "error" });
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Attribute a referral"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSubmit} isLoading={isLoading}>Attribute</Button>
        </>
      }
    >
      <p className="mb-4 text-sm text-white/50">
        Grace-window tool — link a landlord to an affiliate after registration (e.g. "the landlord forgot to
        enter my code"). Only works within the program's attribution grace window, and only if the landlord
        doesn't already have a referral.
      </p>
      <div className="space-y-4">
        <Input label="Search landlord by name/email" value={search} onChange={(e) => setSearch(e.target.value)} />
        <select
          className="glass-input w-full"
          value={landlordId}
          onChange={(e) => setLandlordId(e.target.value)}
        >
          <option value="" className="bg-primary-900">Select landlord…</option>
          {(landlordData?.landlords ?? []).map((l) => (
            <option key={l.id} value={l.id} className="bg-primary-900">{l.company_name}</option>
          ))}
        </select>
        <select
          className="glass-input w-full"
          value={affiliateId}
          onChange={(e) => setAffiliateId(e.target.value)}
        >
          <option value="" className="bg-primary-900">Select affiliate…</option>
          {(affiliateData?.affiliates ?? []).map((a) => (
            <option key={a.id} value={a.id} className="bg-primary-900">{a.full_name} ({a.referral_code})</option>
          ))}
        </select>
      </div>
    </Modal>
  );
}
