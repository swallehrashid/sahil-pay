import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, Ban, RotateCcw, Wrench } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import Modal from "@/components/ui/Modal";
import Textarea from "@/components/ui/Textarea";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import { toast } from "@/components/ui/Toast";
import { useGetAdminLandlordQuery, useSuspendLandlordMutation, useReactivateLandlordMutation, useCorrectDataMutation } from "./adminApiSlice";
import { ADMIN_ROUTES } from "@/config/routePaths";

// §7 — drill into one account; suspend/reactivate after investigation, or correct data.
export default function LandlordDetail() {
  const { id } = useParams();
  const { data, isLoading } = useGetAdminLandlordQuery(id);
  const [suspend, { isLoading: isSuspending }] = useSuspendLandlordMutation();
  const [reactivate, { isLoading: isReactivating }] = useReactivateLandlordMutation();
  const [correctData, { isLoading: isCorrecting }] = useCorrectDataMutation();

  const [isCorrectOpen, setIsCorrectOpen] = useState(false);
  const [note, setNote] = useState("");

  const handleSuspend = async () => {
    try {
      await suspend(id).unwrap();
      toast("Account suspended.", { type: "success" });
    } catch {
      toast("Could not suspend the account.", { type: "error" });
    }
  };

  const handleReactivate = async () => {
    try {
      await reactivate(id).unwrap();
      toast("Account reactivated.", { type: "success" });
    } catch {
      toast("Could not reactivate the account.", { type: "error" });
    }
  };

  const handleCorrect = async (e) => {
    e.preventDefault();
    try {
      await correctData({ landlord_id: id, note }).unwrap();
      toast("Correction logged.", { type: "success" });
      setIsCorrectOpen(false);
      setNote("");
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
            {data?.is_active ? (
              <Button variant="danger" leftIcon={<Ban className="h-4 w-4" />} isLoading={isSuspending} onClick={handleSuspend}>
                Suspend
              </Button>
            ) : (
              <Button leftIcon={<RotateCcw className="h-4 w-4" />} isLoading={isReactivating} onClick={handleReactivate}>
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
          <SummaryCard label="Active tenants" value={data?.active_tenant_count ?? 0} accent="third" />
          <SummaryCard label="Team members" value={data?.team_member_count ?? 0} accent="third" />
        </div>
      )}

      <Modal isOpen={isCorrectOpen} onClose={() => setIsCorrectOpen(false)} title="Correct data">
        <form onSubmit={handleCorrect} className="space-y-4">
          <Textarea label="What needs correcting?" value={note} onChange={(e) => setNote(e.target.value)} rows={4} required />
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
