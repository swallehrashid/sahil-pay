import { useState } from "react";
import { Check, X } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Button from "@/components/ui/Button";
import StatusBadge from "@/components/ui/StatusBadge";
import { toast } from "@/components/ui/Toast";
import { apiSlice } from "@/store/apiSlice";
import { formatDateTime } from "@/utils/dateFormatter";
import { toRows } from "@/utils/tableAdapters";

// Landlord-facing half of the consent-based impersonation workflow (§10.5) — the
// admin-side lives in features/admin/adminImpersonationApiSlice.js. Injected here since
// this is the only landlord page that needs these endpoints.
const landlordImpersonationApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getPendingImpersonationRequests: builder.query({
      query: () => "/admin/impersonation/landlord/pending",
      providesTags: ["Impersonation"],
    }),
    grantImpersonationRequest: builder.mutation({
      query: (id) => ({ url: `/admin/impersonation/landlord/requests/${id}/grant`, method: "POST" }),
      invalidatesTags: ["Impersonation"],
    }),
    denyImpersonationRequest: builder.mutation({
      query: (id) => ({ url: `/admin/impersonation/landlord/requests/${id}/deny`, method: "POST" }),
      invalidatesTags: ["Impersonation"],
    }),
  }),
});

const { useGetPendingImpersonationRequestsQuery, useGrantImpersonationRequestMutation, useDenyImpersonationRequestMutation } =
  landlordImpersonationApiSlice;

export default function ImpersonationRequests() {
  const { data, isLoading } = useGetPendingImpersonationRequestsQuery();
  const [grant] = useGrantImpersonationRequestMutation();
  const [deny] = useDenyImpersonationRequestMutation();
  const [actingId, setActingId] = useState(null);

  const requests = toRows(data);

  const handleGrant = async (id) => {
    setActingId(id);
    try {
      await grant(id).unwrap();
      toast("Access granted.", { type: "success" });
    } catch {
      toast("Could not grant access.", { type: "error" });
    } finally {
      setActingId(null);
    }
  };

  const handleDeny = async (id) => {
    setActingId(id);
    try {
      await deny(id).unwrap();
      toast("Request denied.", { type: "success" });
    } catch {
      toast("Could not deny the request.", { type: "error" });
    } finally {
      setActingId(null);
    }
  };

  const columns = [
    { key: "requested_at", header: "Requested", render: (row) => formatDateTime(row.requested_at) },
    { key: "admin", header: "Admin", render: (row) => row.admin_email ?? row.admin_user_id },
    { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
  ];

  return (
    <div>
      <PageHeader
        title="Impersonation requests"
        subtitle="SahilPay support can only access your account after you explicitly grant a request — never silently."
      />
      <ResponsiveTable
        columns={columns}
        rows={requests}
        isLoading={isLoading}
        emptyState={<p className="text-sm text-white/50">No pending requests.</p>}
        rowActions={(row) => (
          <div className="flex gap-2">
            <Button size="sm" variant="ghost" leftIcon={<Check className="h-4 w-4" />} isLoading={actingId === row.id} onClick={() => handleGrant(row.id)}>
              Grant
            </Button>
            <Button size="sm" variant="danger" leftIcon={<X className="h-4 w-4" />} isLoading={actingId === row.id} onClick={() => handleDeny(row.id)}>
              Deny
            </Button>
          </div>
        )}
      />
    </div>
  );
}
