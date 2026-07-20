import { useState } from "react";
import Modal from "@/components/ui/Modal";
import Select from "@/components/ui/Select";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { useAssignGroupManagerMutation } from "./groupApiSlice";
import { isRequired } from "@/utils/validators";

// Assigns a team member as the manager for a property group (manager_assignments.scope_type='group').
export default function AssignManagerModal({ group, teamMembers = [], onClose }) {
  const [assignManager, { isLoading }] = useAssignGroupManagerMutation();
  const [teamMemberId, setTeamMemberId] = useState("");
  const [error, setError] = useState("");

  if (!group) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!isRequired(teamMemberId)) {
      setError("Select a team member");
      return;
    }
    setError("");
    try {
      await assignManager({ id: group.id, team_member_id: teamMemberId, scope_type: "group" }).unwrap();
      toast(`Manager assigned to ${group.name}.`, { type: "success" });
      onClose();
    } catch {
      toast("Could not assign the manager.", { type: "error" });
    }
  };

  return (
    <Modal isOpen onClose={onClose} title={`Assign manager — ${group.name}`}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <Select
          label="Team member"
          value={teamMemberId}
          onChange={(e) => setTeamMemberId(e.target.value)}
          error={error}
          options={teamMembers.map((m) => ({ value: m.id, label: `${m.first_name} ${m.last_name}` }))}
          required
        />
        <div className="flex justify-end gap-3 pt-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" isLoading={isLoading}>
            Assign manager
          </Button>
        </div>
      </form>
    </Modal>
  );
}
