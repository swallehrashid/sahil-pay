import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useDispatch } from "react-redux";
import { Send, Ban, LogIn } from "lucide-react";
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
import { apiSlice } from "@/store/apiSlice";
import { setImpersonationTarget } from "@/utils/impersonationStorage";
import { LANDLORD_ROUTES } from "@/config/routePaths";
import { formatDateTime } from "@/utils/dateFormatter";
import { toRows } from "@/utils/tableAdapters";

// §7.3 / §10.5 — consent-based: admin requests, landlord grants, then admin may operate
// the account. Never a silent backdoor — everything is also written to audit_logs.
export default function Impersonation() {
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const { data, isLoading } = useGetImpersonationRequestsQuery();
  const { data: landlordsData } = useGetAdminLandlordsQuery();
  const [requestAccess, { isLoading: isRequesting }] = useRequestImpersonationMutation();
  const [revoke] = useRevokeImpersonationMutation();

  const handleEnterSession = (row) => {
    setImpersonationTarget({ landlordId: row.landlord_id, companyName: row.landlord_company });
    // A different impersonation target must never see another's cached query results.
    dispatch(apiSlice.util.resetApiState());
    navigate(LANDLORD_ROUTES.dashboard);
  };

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
    { key: "landlord", header: "Landlord", render: (row) => row.landlord_company },
    { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
    { key: "requested_at", header: "Requested", render: (row) => formatDateTime(row.requested_at) },
    { key: "expires_at", header: "Expires", render: (row) => (row.expires_at ? formatDateTime(row.expires_at) : "—") },
  ];

  const isActiveGrant = (row) => row.status === "granted" && (!row.expires_at || new Date(row.expires_at) > new Date());

  return (
    <div>
      <PageHeader
        title="Client Support"
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
          isActiveGrant(row) && (
            <div className="flex gap-2">
              <Button size="sm" leftIcon={<LogIn className="h-4 w-4" />} onClick={() => handleEnterSession(row)}>
                Enter session
              </Button>
              <Button
                size="sm"
                variant="danger"
                leftIcon={<Ban className="h-4 w-4" />}
                onClick={() => revoke(row.id).then(() => toast("Session revoked.", { type: "success" }))}
              >
                Revoke
              </Button>
            </div>
          )
        }
      />

      <Modal isOpen={isRequestOpen} onClose={() => setIsRequestOpen(false)} title="Request client support access">
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
