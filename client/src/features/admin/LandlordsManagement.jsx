import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Eye, Ban, RotateCcw } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import Input from "@/components/ui/Input";
import Textarea from "@/components/ui/Textarea";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Dropdown from "@/components/ui/Dropdown";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Badge from "@/components/ui/Badge";
import { useDebounce } from "@/hooks/useDebounce";
import { toast } from "@/components/ui/Toast";
import { useGetAdminLandlordsQuery, useSuspendLandlordMutation, useReactivateLandlordMutation } from "./adminApiSlice";
import { toRows } from "@/utils/tableAdapters";
import { ADMIN_ROUTES } from "@/config/routePaths";

// §7 — list/search every registered account.
export default function LandlordsManagement() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebounce(search);

  const { data, isLoading } = useGetAdminLandlordsQuery({ search: debouncedSearch });
  const [suspend, { isLoading: isSuspending }] = useSuspendLandlordMutation();
  const [reactivate, { isLoading: isReactivating }] = useReactivateLandlordMutation();

  // Suspend/reactivate both require a mandatory reason — collected via this dialog.
  const [pendingChange, setPendingChange] = useState(null); // { id, company_name, action } | null
  const [reason, setReason] = useState("");

  const handleConfirm = async () => {
    if (!reason.trim()) {
      toast("A reason is required.", { type: "error" });
      return;
    }
    try {
      if (pendingChange.action === "suspend") {
        await suspend({ id: pendingChange.id, reason }).unwrap();
        toast("Account suspended.", { type: "success" });
      } else {
        await reactivate({ id: pendingChange.id, reason }).unwrap();
        toast("Account reactivated.", { type: "success" });
      }
      setPendingChange(null);
      setReason("");
    } catch {
      toast(`Could not ${pendingChange.action} the account.`, { type: "error" });
    }
  };

  const rows = toRows(data);

  const columns = [
    { key: "company_name", header: "Company" },
    { key: "account_type", header: "Account type" },
    { key: "units", header: "Units", render: (row) => row.unit_count ?? 0 },
    {
      key: "status",
      header: "Status",
      render: (row) => <Badge color={row.is_active ? "emerald" : "secondary"}>{row.is_active ? "Active" : "Suspended"}</Badge>,
    },
  ];

  return (
    <div>
      <PageHeader title="Landlords" subtitle="Search and manage registered accounts" />

      <Input className="mb-6 max-w-sm" placeholder="Search by company name…" value={search} onChange={(e) => setSearch(e.target.value)} />

      <ResponsiveTable
        columns={columns}
        rows={rows}
        isLoading={isLoading}
        onRowClick={(row) => navigate(ADMIN_ROUTES.landlordDetailPath(row.id))}
        rowActions={(row) => (
          <Dropdown
            items={[
              { label: "View detail", icon: <Eye className="h-4 w-4" />, onClick: () => navigate(ADMIN_ROUTES.landlordDetailPath(row.id)) },
              row.is_active
                ? {
                    label: "Suspend",
                    icon: <Ban className="h-4 w-4" />,
                    danger: true,
                    onClick: () => setPendingChange({ id: row.id, company_name: row.company_name, action: "suspend" }),
                  }
                : {
                    label: "Reactivate",
                    icon: <RotateCcw className="h-4 w-4" />,
                    onClick: () => setPendingChange({ id: row.id, company_name: row.company_name, action: "reactivate" }),
                  },
            ]}
          />
        )}
      />

      <ConfirmDialog
        isOpen={Boolean(pendingChange)}
        onClose={() => { setPendingChange(null); setReason(""); }}
        onConfirm={handleConfirm}
        title={pendingChange?.action === "suspend" ? `Suspend ${pendingChange?.company_name}?` : `Reactivate ${pendingChange?.company_name}?`}
        description="This is recorded in the audit trail with your reason."
        isDangerous={pendingChange?.action === "suspend"}
        isLoading={isSuspending || isReactivating}
        confirmLabel={pendingChange?.action === "suspend" ? "Suspend" : "Reactivate"}
      >
        <Textarea label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={3} required className="mt-3" />
      </ConfirmDialog>
    </div>
  );
}
