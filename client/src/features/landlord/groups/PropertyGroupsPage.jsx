import { useState } from "react";
import { Plus, Pencil, Trash2, UserCog } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Dropdown from "@/components/ui/Dropdown";
import Modal from "@/components/ui/Modal";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import GroupForm from "./GroupForm";
import AssignManagerModal from "./AssignManagerModal";
import { useGetPropertyGroupsQuery, useCreatePropertyGroupMutation, useUpdatePropertyGroupMutation, useDeletePropertyGroupMutation } from "./groupApiSlice";
import { useGetPropertiesQuery } from "../properties/propertyApiSlice";
import { useGetTeamMembersQuery } from "../settings/teamApiSlice";
import { toRows } from "@/utils/tableAdapters";

export default function PropertyGroupsPage() {
  const { data, isLoading } = useGetPropertyGroupsQuery();
  const { data: propertiesData } = useGetPropertiesQuery();
  const { data: teamData } = useGetTeamMembersQuery();
  const [createGroup, { isLoading: isCreating }] = useCreatePropertyGroupMutation();
  const [updateGroup, { isLoading: isUpdating }] = useUpdatePropertyGroupMutation();
  const [deleteGroup] = useDeletePropertyGroupMutation();

  const [active, setActive] = useState(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [assignTarget, setAssignTarget] = useState(null);
  const [pendingDelete, setPendingDelete] = useState(null);

  const groups = toRows(data);
  const properties = toRows(propertiesData);
  const teamMembers = toRows(teamData);

  const handleSubmit = async (values) => {
    try {
      if (active?.id) {
        await updateGroup({ id: active.id, ...values }).unwrap();
        toast("Group updated.", { type: "success" });
      } else {
        await createGroup(values).unwrap();
        toast("Group created.", { type: "success" });
      }
      setIsFormOpen(false);
    } catch {
      toast("Could not save the group.", { type: "error" });
    }
  };

  const handleDelete = async () => {
    try {
      await deleteGroup(pendingDelete.id).unwrap();
      toast("Group deleted.", { type: "success" });
    } catch {
      toast("Could not delete the group.", { type: "error" });
    } finally {
      setPendingDelete(null);
    }
  };

  const columns = [
    { key: "name", header: "Group" },
    { key: "properties", header: "Properties", render: (row) => row.property_count ?? row.property_ids?.length ?? 0 },
    { key: "manager", header: "Manager", render: (row) => row.manager_name ?? "Unassigned" },
  ];

  return (
    <div>
      <PageHeader
        title="Property Groups"
        subtitle="Organize properties for reporting and manager assignment"
        actions={
          <Button
            leftIcon={<Plus className="h-4 w-4" />}
            onClick={() => {
              setActive(null);
              setIsFormOpen(true);
            }}
          >
            Add group
          </Button>
        }
      />

      <ResponsiveTable
        columns={columns}
        rows={groups}
        isLoading={isLoading}
        emptyState={<p className="text-sm text-white/50">No property groups yet.</p>}
        rowActions={(row) => (
          <Dropdown
            items={[
              { label: "Assign manager", icon: <UserCog className="h-4 w-4" />, onClick: () => setAssignTarget(row) },
              {
                label: "Edit",
                icon: <Pencil className="h-4 w-4" />,
                onClick: () => {
                  setActive(row);
                  setIsFormOpen(true);
                },
              },
              { label: "Delete", icon: <Trash2 className="h-4 w-4" />, danger: true, onClick: () => setPendingDelete(row) },
            ]}
          />
        )}
      />

      <Modal isOpen={isFormOpen} onClose={() => setIsFormOpen(false)} title={active ? "Edit group" : "Add group"}>
        <GroupForm initialValues={active} properties={properties} onSubmit={handleSubmit} onCancel={() => setIsFormOpen(false)} isSubmitting={isCreating || isUpdating} />
      </Modal>

      <AssignManagerModal group={assignTarget} teamMembers={teamMembers} onClose={() => setAssignTarget(null)} />

      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        onConfirm={handleDelete}
        title="Delete group?"
        description={`"${pendingDelete?.name}" will be permanently removed.`}
      />
    </div>
  );
}
