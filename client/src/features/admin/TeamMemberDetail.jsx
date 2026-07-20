import { useParams, Link } from "react-router-dom";
import { ArrowLeft, Check, X } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import DetailGrid from "./components/DetailGrid";
import { useGetAdminTeamMemberQuery } from "./adminApiSlice";
import { formatDateTime } from "@/utils/dateFormatter";
import { ADMIN_ROUTES } from "@/config/routePaths";

const YesNo = ({ on }) =>
  on ? <Check className="h-4 w-4 text-emerald-400" /> : <X className="h-4 w-4 text-white/25" />;

// §7 — full team-member detail: who they belong to, what they can do
// (per-module permissions), their property scope, and what they've been doing.
export default function TeamMemberDetail() {
  const { id } = useParams();
  const { data, isLoading } = useGetAdminTeamMemberQuery(id);

  const name = data ? [data.first_name, data.last_name].filter(Boolean).join(" ") || data.username : "";
  const propertyAccess = data?.property_access;

  return (
    <div className="space-y-6">
      <PageHeader
        title={name || "Team member"}
        subtitle={data?.landlord?.company_name ? `Belongs to ${data.landlord.company_name}` : "Team member detail"}
        breadcrumbs={[{ label: "Team members", to: ADMIN_ROUTES.teamMembers }, { label: "Detail" }]}
        actions={
          <Link to={ADMIN_ROUTES.teamMembers}>
            <Button variant="ghost" leftIcon={<ArrowLeft className="h-4 w-4" />}>Back</Button>
          </Link>
        }
      />

      {isLoading ? (
        <SkeletonStatCards count={4} />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          <SummaryCard label="Status" value={<Badge color={data?.is_active ? "emerald" : "secondary"}>{data?.is_active ? "Active" : "Pending"}</Badge>} />
          <SummaryCard label="Role" value={data?.role ?? "—"} accent="third" />
          <SummaryCard label="Modules granted" value={data?.permissions?.filter((p) => p.can_view || p.can_edit).length ?? 0} accent="third" />
          <SummaryCard label="Recent actions" value={data?.recent_activity?.length ?? 0} accent="third" />
        </div>
      )}

      <DetailGrid
        title="Profile"
        items={[
          { label: "Username", value: data?.username },
          { label: "Name", value: name },
          { label: "Email", value: data?.email },
          { label: "Phone", value: data?.phone },
          { label: "Role", value: data?.role },
          { label: "Belongs to", value: data?.landlord?.company_name && (
            <Link className="text-third-100 hover:underline" to={ADMIN_ROUTES.landlordDetailPath(data.landlord.landlord_id)}>{data.landlord.company_name}</Link>
          ) },
        ]}
      />

      <div className="glass p-6">
        <h3 className="mb-4 text-sm font-medium text-white/70">Permissions — what they can do</h3>
        <ResponsiveTable
          columns={[
            { key: "module", header: "Module" },
            { key: "can_view", header: "View", render: (r) => <YesNo on={r.can_view} /> },
            { key: "can_edit", header: "Edit", render: (r) => <YesNo on={r.can_edit} /> },
          ]}
          rows={data?.permissions ?? []}
          isLoading={isLoading}
        />
      </div>

      <div className="glass p-6">
        <h3 className="mb-3 text-sm font-medium text-white/70">Property access</h3>
        {propertyAccess === "all" ? (
          <Badge color="emerald">All properties</Badge>
        ) : Array.isArray(propertyAccess) && propertyAccess.length ? (
          <div className="flex flex-wrap gap-2">
            {propertyAccess.map((p) => (
              <Badge key={p.id} color="third">{p.name}{p.city ? ` · ${p.city}` : ""}</Badge>
            ))}
          </div>
        ) : (
          <p className="text-sm text-white/40">No properties assigned.</p>
        )}
      </div>

      <div className="glass p-6">
        <h3 className="mb-4 text-sm font-medium text-white/70">Recent activity — what they've been doing</h3>
        <ResponsiveTable
          columns={[
            { key: "created_at", header: "When", render: (r) => formatDateTime(r.created_at) },
            { key: "action", header: "Action" },
            { key: "entity_type", header: "Entity", render: (r) => `${r.entity_type ?? ""}${r.entity_id ? ` #${r.entity_id}` : ""}` },
            { key: "description", header: "Description" },
          ]}
          rows={data?.recent_activity ?? []}
          isLoading={isLoading}
        />
      </div>
    </div>
  );
}
