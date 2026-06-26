import { useState } from "react";
import { Send, Ban } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Modal from "@/components/ui/Modal";
import Select from "@/components/ui/Select";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import StatusBadge from "@/components/ui/StatusBadge";
import { toast } from "@/components/ui/Toast";
import { useGetImpersonationRequestsQuery, useRequestImpersonationMutation, useRevokeImpersonationMutation } from "./adminImpersonationApiSlice";
import { useGetAdminLandlordsQuery } from "./adminApiSlice";
import { formatDateTime } from "@/utils/dateFormatter";
import { toRows } from "@/utils/tableAdapters";

// §7.3 / §10.5 — consent-based: admin requests, landlord grants, then admin may operate
// the account. Never a silent backdoor — everything is also written to audit_logs.
export default function Impersonation() {
  const { data, isLoading } = useGetImpersonationRequestsQuery();
  const { data: landlordsData } = useGetAdminLandlordsQuery();
  const [requestAccess, { isLoading: isRequesting }] = useRequestImpersonationMutation();
  const [revoke] = useRevokeImpersonationMutation();

  const [isRequestOpen, setIsRequestOpen] = useState(false);
  const [landlordId, setLandlordId] = useState("");
  const [reason, setReason] = useState("");

  const requests = toRows(data);
  const landlords = toRows(landlordsData);

  const handleRequest = async (e) => {
    e.preventDefault();
    // Backend requires both landlord_id AND reason — omitting reason 400s.
    try {
      await requestAccess({ landlord_id: landlordId, reason }).unwrap();
      toast("Request sent — waiting for the landlord to grant access.", { type: "success" });
      setIsRequestOpen(false);
      setLandlordId("");
      setReason("");
    } catch {
      toast("Could not send the request.", { type: "error" });
    }
  };

  const columns = [
    { key: "landlord", header: "Landlord", render: (row) => row.company_name },
    { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
    { key: "requested_at", header: "Requested", render: (row) => formatDateTime(row.requested_at) },
    { key: "expires_at", header: "Expires", render: (row) => (row.expires_at ? formatDateTime(row.expires_at) : "—") },
  ];

  return (
    <div>
      <PageHeader
        title="Impersonation"
        subtitle="Request consent-based access to assist a landlord"
        actions={
          <Button leftIcon={<Send className="h-4 w-4" />} onClick={() => setIsRequestOpen(true)}>
            Request access
          </Button>
        }
      />

      <ResponsiveTable
        columns={columns}
        rows={requests}
        isLoading={isLoading}
        rowActions={(row) =>
          row.status === "granted" && (
            <Button
              size="sm"
              variant="danger"
              leftIcon={<Ban className="h-4 w-4" />}
              onClick={() => revoke(row.id).then(() => toast("Session revoked.", { type: "success" }))}
            >
              Revoke
            </Button>
          )
        }
      />

      <Modal isOpen={isRequestOpen} onClose={() => setIsRequestOpen(false)} title="Request impersonation access">
        <form onSubmit={handleRequest} className="space-y-4">
          <Select
            label="Landlord"
            value={landlordId}
            onChange={(e) => setLandlordId(e.target.value)}
            options={landlords.map((l) => ({ value: l.id, label: l.company_name }))}
            required
          />
          <Input
            label="Reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Why you need access (shown to the landlord)"
            required
          />
          <p className="text-xs text-white/40">The landlord will see this request and must explicitly grant it before you gain access.</p>
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="ghost" onClick={() => setIsRequestOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" isLoading={isRequesting}>
              Send request
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
