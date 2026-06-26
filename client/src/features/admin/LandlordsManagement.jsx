import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Eye, Ban, RotateCcw } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import Input from "@/components/ui/Input";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Dropdown from "@/components/ui/Dropdown";
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
  const [suspend] = useSuspendLandlordMutation();
  const [reactivate] = useReactivateLandlordMutation();

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
                    onClick: () => suspend(row.id).then(() => toast("Account suspended.", { type: "success" })),
                  }
                : {
                    label: "Reactivate",
                    icon: <RotateCcw className="h-4 w-4" />,
                    onClick: () => reactivate(row.id).then(() => toast("Account reactivated.", { type: "success" })),
                  },
            ]}
          />
        )}
      />
    </div>
  );
}
