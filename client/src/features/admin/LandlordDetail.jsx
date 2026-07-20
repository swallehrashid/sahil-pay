import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, Ban, RotateCcw, Wrench, Smartphone } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import Modal from "@/components/ui/Modal";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Textarea from "@/components/ui/Textarea";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import { toast } from "@/components/ui/Toast";
import { useGetAdminLandlordQuery, useSuspendLandlordMutation, useReactivateLandlordMutation, useCorrectDataMutation } from "./adminApiSlice";
import { ADMIN_ROUTES } from "@/config/routePaths";

const CORRECTION_ENTITY_TYPES = [
  { value: "tenant", label: "Tenant" },
  { value: "payment", label: "Payment" },
  { value: "invoice", label: "Invoice" },
];

// §7 — drill into one account; suspend/reactivate after investigation, or correct data.
export default function LandlordDetail() {
  const { id } = useParams();
  const { data, isLoading } = useGetAdminLandlordQuery(id);
  const [suspend, { isLoading: isSuspending }] = useSuspendLandlordMutation();
  const [reactivate, { isLoading: isReactivating }] = useReactivateLandlordMutation();
  const [correctData, { isLoading: isCorrecting }] = useCorrectDataMutation();

  const [isCorrectOpen, setIsCorrectOpen] = useState(false);
  const [correction, setCorrection] = useState({ entity_type: "tenant", entity_id: "", correction_json: "{}", reason: "" });
  const [correctionError, setCorrectionError] = useState("");

  // Suspend/reactivate both require a mandatory reason — collected via the same dialog.
  const [pendingStatusChange, setPendingStatusChange] = useState(null); // "suspend" | "reactivate" | null
  const [statusReason, setStatusReason] = useState("");

  const handleConfirmStatusChange = async () => {
    if (!statusReason.trim()) {
      toast("A reason is required.", { type: "error" });
      return;
    }
    try {
      if (pendingStatusChange === "suspend") {
        await suspend({ id, reason: statusReason }).unwrap();
        toast("Account suspended.", { type: "success" });
      } else {
        await reactivate({ id, reason: statusReason }).unwrap();
        toast("Account reactivated.", { type: "success" });
      }
      setPendingStatusChange(null);
      setStatusReason("");
    } catch {
      toast(`Could not ${pendingStatusChange} the account.`, { type: "error" });
    }
  };

  const handleCorrect = async (e) => {
    e.preventDefault();
    let parsedCorrection;
    try {
      parsedCorrection = JSON.parse(correction.correction_json);
    } catch {
      setCorrectionError("Correction must be valid JSON, e.g. {\"notes\": \"fixed typo\"}");
      return;
    }
    if (!correction.entity_id || !correction.reason.trim()) {
      setCorrectionError("Entity ID and reason are required.");
      return;
    }
    setCorrectionError("");
    try {
      await correctData({
        landlord_id: Number(id),
        entity_type: correction.entity_type,
        entity_id: Number(correction.entity_id),
        correction: parsedCorrection,
        reason: correction.reason,
      }).unwrap();
      toast("Correction logged.", { type: "success" });
      setIsCorrectOpen(false);
      setCorrection({ entity_type: "tenant", entity_id: "", correction_json: "{}", reason: "" });
    } catch {
      toast("Could not submit the correction.", { type: "error" });
    }
  };

  return (
    <div>
      <PageHeader
        title={data?.company_name ?? "Landlord detail"}
        subtitle="Drill into this account"
        breadcrumbs={[{ label: "Landlords", to: ADMIN_ROUTES.landlords }, { label: "Detail" }]}
        actions={
          <>
            <Link to={ADMIN_ROUTES.landlords}>
              <Button variant="ghost" leftIcon={<ArrowLeft className="h-4 w-4" />}>
                Back
              </Button>
            </Link>
            <Button variant="ghost" leftIcon={<Wrench className="h-4 w-4" />} onClick={() => setIsCorrectOpen(true)}>
              Correct data
            </Button>
            <Link to={`${ADMIN_ROUTES.copilot}?tab=landlords&landlord_id=${id}`}>
              <Button variant="ghost" leftIcon={<Smartphone className="h-4 w-4" />}>
                Co-pilot
              </Button>
            </Link>
            {data?.is_active ? (
              <Button variant="danger" leftIcon={<Ban className="h-4 w-4" />} onClick={() => setPendingStatusChange("suspend")}>
                Suspend
              </Button>
            ) : (
              <Button leftIcon={<RotateCcw className="h-4 w-4" />} onClick={() => setPendingStatusChange("reactivate")}>
                Reactivate
              </Button>
            )}
          </>
        }
      />

      {isLoading ? (
        <SkeletonStatCards count={4} />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
          <SummaryCard label="Status" value={<Badge color={data?.is_active ? "emerald" : "secondary"}>{data?.is_active ? "Active" : "Suspended"}</Badge>} />
          <SummaryCard label="Units" value={data?.unit_count ?? 0} accent="third" />
          <SummaryCard label="Active tenants" value={data?.active_tenants ?? 0} accent="third" />
          <SummaryCard label="Team members" value={data?.team_members?.length ?? 0} accent="third" />
        </div>
      )}

      <ConfirmDialog
        isOpen={Boolean(pendingStatusChange)}
        onClose={() => { setPendingStatusChange(null); setStatusReason(""); }}
        onConfirm={handleConfirmStatusChange}
        title={pendingStatusChange === "suspend" ? "Suspend this account?" : "Reactivate this account?"}
        description="This is recorded in the audit trail with your reason."
        isDangerous={pendingStatusChange === "suspend"}
        isLoading={isSuspending || isReactivating}
        confirmLabel={pendingStatusChange === "suspend" ? "Suspend" : "Reactivate"}
      >
        <Textarea
          label="Reason"
          value={statusReason}
          onChange={(e) => setStatusReason(e.target.value)}
          rows={3}
          required
          className="mt-3"
        />
      </ConfirmDialog>

      <Modal isOpen={isCorrectOpen} onClose={() => setIsCorrectOpen(false)} title="Correct data">
        <form onSubmit={handleCorrect} className="space-y-4">
          <Select
            label="Entity type"
            value={correction.entity_type}
            onChange={(e) => setCorrection((c) => ({ ...c, entity_type: e.target.value }))}
            options={CORRECTION_ENTITY_TYPES}
            required
          />
          <Input
            label="Entity ID"
            type="number"
            value={correction.entity_id}
            onChange={(e) => setCorrection((c) => ({ ...c, entity_id: e.target.value }))}
            required
          />
          <Textarea
            label="Correction (JSON)"
            hint='Only a limited safe field set per entity is allowed, e.g. {"notes": "corrected typo"}'
            value={correction.correction_json}
            onChange={(e) => setCorrection((c) => ({ ...c, correction_json: e.target.value }))}
            rows={4}
            required
          />
          <Textarea
            label="Reason"
            value={correction.reason}
            onChange={(e) => setCorrection((c) => ({ ...c, reason: e.target.value }))}
            rows={2}
            required
          />
          {correctionError && <p className="text-xs text-secondary-300">{correctionError}</p>}
          <div className="flex justify-end gap-3 pt-2">
            <Button type="button" variant="ghost" onClick={() => setIsCorrectOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" isLoading={isCorrecting}>
              Submit correction
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
