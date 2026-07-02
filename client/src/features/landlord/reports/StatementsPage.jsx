import { useState } from "react";
import PageHeader from "@/components/layout/PageHeader";
import Tabs from "@/components/ui/Tabs";
import TenantStatement from "./TenantStatement";
import PropertyStatement from "./PropertyStatement";
import ArrearsReport from "./ArrearsReport";
import ExpensesReport from "./ExpensesReport";
import MonthOnMonthReport from "./MonthOnMonthReport";
import YearOnYearReport from "./YearOnYearReport";
import GroupingReport from "./GroupingReport";
import DeletedTenantsReport from "./DeletedTenantsReport";
import { useGetTenantsQuery } from "../tenants/tenantApiSlice";
import { useGetPropertiesQuery } from "../properties/propertyApiSlice";
import { useGetPropertyGroupsQuery } from "../groups/groupApiSlice";
import { toRows } from "@/utils/tableAdapters";

const TABS = [
  { key: "tenant", label: "Tenant Statement" },
  { key: "property", label: "Property Statement" },
  { key: "arrears", label: "Arrears" },
  { key: "expenses", label: "Expenses" },
  { key: "mom", label: "Month-on-Month" },
  { key: "yoy", label: "Year-on-Year" },
  { key: "grouping", label: "Grouping" },
  { key: "deleted", label: "Deleted Tenants" },
];

// §4.11 — hub for every statement type. Each generates an on-screen preview with
// editable columns (and graphs where relevant), then exports to PDF/Excel with
// the landlord's letterhead + signature.
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
      {tab === "mom" && <MonthOnMonthReport properties={properties} />}
      {tab === "yoy" && <YearOnYearReport properties={properties} />}
      {tab === "grouping" && <GroupingReport groups={groups} />}
      {tab === "deleted" && <DeletedTenantsReport properties={properties} />}
    </div>
  );
}
