import { useState } from "react";
import PageHeader from "@/components/layout/PageHeader";
import Tabs from "@/components/ui/Tabs";
import TenantStatement from "./TenantStatement";
import PropertyStatement from "./PropertyStatement";
import ArrearsReport from "./ArrearsReport";
import ExpensesReport from "./ExpensesReport";
import ComparativeReport from "./ComparativeReport";
import GroupingReport from "./GroupingReport";
import { useGetTenantsQuery } from "../tenants/tenantApiSlice";
import { useGetPropertiesQuery } from "../properties/propertyApiSlice";
import { useGetPropertyGroupsQuery } from "../groups/groupApiSlice";
import { toRows } from "@/utils/tableAdapters";

const TABS = [
  { key: "tenant", label: "Tenant Statement" },
  { key: "property", label: "Property Statement" },
  { key: "arrears", label: "Arrears" },
  { key: "expenses", label: "Expenses" },
  { key: "comparative", label: "Comparative" },
  { key: "grouping", label: "Grouping" },
];

// §4.11 — hub for every statement type. Each generates on demand and exports to PDF/Excel.
export default function StatementsPage() {
  const [tab, setTab] = useState("tenant");
  const { data: tenantsData } = useGetTenantsQuery();
  const { data: propertiesData } = useGetPropertiesQuery();
  const { data: groupsData } = useGetPropertyGroupsQuery();

  const tenants = toRows(tenantsData);
  const properties = toRows(propertiesData);
  const groups = toRows(groupsData);

  return (
    <div>
      <PageHeader title="Statements" subtitle="Generate and export detailed financial statements" />
      <Tabs tabs={TABS} activeKey={tab} onChange={setTab} className="mb-6" />
      {tab === "tenant" && <TenantStatement tenants={tenants} />}
      {tab === "property" && <PropertyStatement properties={properties} />}
      {tab === "arrears" && <ArrearsReport properties={properties} />}
      {tab === "expenses" && <ExpensesReport properties={properties} />}
      {tab === "comparative" && <ComparativeReport />}
      {tab === "grouping" && <GroupingReport groups={groups} />}
    </div>
  );
}
