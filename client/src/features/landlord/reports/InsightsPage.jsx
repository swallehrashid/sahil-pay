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

// Maps a tab key to the matching sub-list key in each per-property insights entry.
const SEGMENT_KEY = { arrears: "arrears", advances: "advances", zero: "zero_balance" };

// §4.12 — per-property arrears/advances/zero-arrears split, plus an Occupancy tab.
export default function InsightsPage() {
  const navigate = useNavigate();
  const [tab, setTab] = useState("arrears");
  const [propertyId, setPropertyId] = useState("");

  const { data: propertiesData } = useGetPropertiesQuery();
  // Backend has no server-side segment filter — it always returns all three
  // segments nested per property; the tab selection is applied client-side below.
  const { data, isLoading } = useGetInsightsQuery({ property_id: propertyId }, { skip: tab === "occupancy" });
  const [sendReminder] = useSendTenantReminderMutation();
  const [sendStatement] = useSendTenantStatementMutation();

  const properties = toRows(propertiesData);
  // Flatten the per-property { arrears, advances, zero_balance } entries for the
  // selected tab into one tenant-row list, carrying the parent property's name.
  const rows = (data?.insights ?? []).flatMap((p) =>
    (p[SEGMENT_KEY[tab]] ?? []).map((t) => ({ ...t, property_name: p.property_name }))
  );

  const columns = [
    { key: "tenant", header: "Tenant", render: (row) => row.name },
    { key: "property", header: "Property", render: (row) => row.property_name },
    { key: "balance", header: "Balance", render: (row) => (row.balance !== undefined ? formatCurrency(row.balance) : "—") },
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
                { label: "View transactions", icon: <Eye className="h-4 w-4" />, onClick: () => navigate(LANDLORD_ROUTES.tenantTransactionsPath(row.tenant_id)) },
                {
                  label: "Reminder",
                  icon: <Bell className="h-4 w-4" />,
                  onClick: () => sendReminder(row.tenant_id).then(() => toast("Reminder sent.", { type: "success" })),
                },
                {
                  label: "Send statement",
                  icon: <FileDown className="h-4 w-4" />,
                  onClick: () => sendStatement(row.tenant_id).then(() => toast("Statement sent.", { type: "success" })),
                },
                {
                  label: "Download CSV",
                  icon: <FileDown className="h-4 w-4" />,
                  onClick: () => downloadFile(`/tenants/${row.tenant_id}/export.csv`, { filename: `${row.name}.csv`, format: "csv" }),
                },
              ]}
            />
          )}
        />
      )}
    </div>
  );
}
