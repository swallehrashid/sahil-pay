import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Eye, Bell, FileDown } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import Tabs from "@/components/ui/Tabs";
import Select from "@/components/ui/Select";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Dropdown from "@/components/ui/Dropdown";
import { toast } from "@/components/ui/Toast";
import OccupancyInsights from "./OccupancyInsights";
import { useGetInsightsQuery } from "./reportApiSlice";
import { useGetPropertiesQuery } from "../properties/propertyApiSlice";
import { useSendTenantReminderMutation, useSendTenantStatementMutation } from "../tenants/tenantApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { downloadFile } from "@/utils/downloadFile";
import { toRows } from "@/utils/tableAdapters";
import { LANDLORD_ROUTES } from "@/config/routePaths";

const SEGMENTS = [
  { key: "arrears", label: "Tenants in arrears" },
  { key: "advances", label: "Tenants with advances" },
  { key: "zero", label: "Zero arrears" },
];

// §4.12 — per-property arrears/advances/zero-arrears split, plus an Occupancy tab.
export default function InsightsPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState("arrears");
  const [propertyId, setPropertyId] = useState("");

  const { data: propertiesData } = useGetPropertiesQuery();
  const { data, isLoading } = useGetInsightsQuery({ property_id: propertyId, segment: tab }, { skip: tab === "occupancy" });
  const [sendReminder] = useSendTenantReminderMutation();
  const [sendStatement] = useSendTenantStatementMutation();

  const properties = toRows(propertiesData);
  const rows = toRows(data);

  const columns = [
    { key: "tenant", header: "Tenant", render: (row) => `${row.first_name} ${row.last_name}` },
    { key: "property", header: "Property", render: (row) => row.property_name },
    { key: "balance", header: "Balance", render: (row) => formatCurrency(row.balance) },
  ];

  return (
    <div>
      <PageHeader title="Insights" subtitle="Arrears, advances and occupancy at a glance" />

      <Select
        label="Property"
        value={propertyId}
        onChange={(e) => setPropertyId(e.target.value)}
        placeholder="All properties"
        options={properties.map((p) => ({ value: p.id, label: p.name }))}
        className="mb-6 max-w-xs"
      />

      <Tabs tabs={[...SEGMENTS, { key: "occupancy", label: "Occupancy" }]} activeKey={tab} onChange={setTab} className="mb-6" />

      {tab === "occupancy" ? (
        <OccupancyInsights propertyId={propertyId} />
      ) : (
        <ResponsiveTable
          columns={columns}
          rows={rows}
          isLoading={isLoading}
          rowActions={(row) => (
            <Dropdown
              items={[
                { label: "View transactions", icon: <Eye className="h-4 w-4" />, onClick: () => navigate(LANDLORD_ROUTES.tenantTransactionsPath(row.id)) },
                {
                  label: "Reminder",
                  icon: <Bell className="h-4 w-4" />,
                  onClick: () => sendReminder(row.id).then(() => toast("Reminder sent.", { type: "success" })),
                },
                {
                  label: "Send statement",
                  icon: <FileDown className="h-4 w-4" />,
                  onClick: () => sendStatement(row.id).then(() => toast("Statement sent.", { type: "success" })),
                },
                {
                  label: "Download CSV",
                  icon: <FileDown className="h-4 w-4" />,
                  onClick: () => downloadFile(`/tenants/${row.id}/export.csv`, { filename: `${row.first_name}.csv`, format: "csv" }),
                },
              ]}
            />
          )}
        />
      )}
    </div>
  );
}
