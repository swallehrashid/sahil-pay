import { useState } from "react";
import { Plus, Pencil, Trash2 } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Dropdown from "@/components/ui/Dropdown";
import Modal from "@/components/ui/Modal";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import { toast } from "@/components/ui/Toast";
import TeamMemberForm from "./TeamMemberForm";
import {
  useGetTeamMembersQuery, useCreateTeamMemberMutation, useUpdateTeamMemberMutation,
  useDeleteTeamMemberMutation, useUpdateTeamMemberPermissionsMutation, useUpdateTeamMemberPropertyAccessMutation,
} from "./teamApiSlice";
import { useGetPropertiesQuery } from "../properties/propertyApiSlice";
import { toRows } from "@/utils/tableAdapters";

// §4.20 — team table + add/edit/remove member.
export default function TeamManagement() {
  const { data, isLoading } = useGetTeamMembersQuery();
  const { data: propertiesData } = useGetPropertiesQuery();
  const [createMember, { isLoading: isCreating }] = useCreateTeamMemberMutation();
  const [updateMember, { isLoading: isUpdating }] = useUpdateTeamMemberMutation();
  const [deleteMember] = useDeleteTeamMemberMutation();
  const [updatePermissions] = useUpdateTeamMemberPermissionsMutation();
  const [updatePropertyAccess] = useUpdateTeamMemberPropertyAccessMutation();

  const [active, setActive] = useState(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);

  // Backend returns { team_members: [...] }, not one of toRows()'s recognized keys.
  const members = data?.team_members ?? [];
  const properties = toRows(propertiesData);

  const handleSubmit = async (values) => {
    const { permissions, property_ids, property_access_all, ...baseFields } = values;
    try {
      let memberId = active?.id;
      if (memberId) {
        await updateMember({ id: memberId, ...baseFields, property_access_all }).unwrap();
        toast("Team member updated.", { type: "success" });
      } else {
        const result = await createMember({ ...baseFields, property_access_all }).unwrap();
        memberId = result?.team_member?.id;
        toast("Team member invited.", { type: "success" });
      }

      // create/update only persist base fields — permissions and property scope
      // are separate endpoints by design (server/routes/team_routes.py).
      const permissionsPayload = Object.entries(permissions ?? {}).map(([module, p]) => ({
        module, can_view: p.can_view, can_edit: p.can_edit,
      }));
      if (memberId && permissionsPayload.length) {
        await updatePermissions({ id: memberId, permissions: permissionsPayload }).unwrap();
      }
      if (memberId) {
        await updatePropertyAccess({ id: memberId, property_access_all, property_ids: property_ids ?? [] }).unwrap();
      }

      setIsFormOpen(false);
    } catch {
      toast("Could not save the team member.", { type: "error" });
    }
  };

  const handleDelete = async () => {
    try {
      await deleteMember(pendingDelete.id).unwrap();
      toast("Team member removed.", { type: "success" });
    } catch {
      toast("Could not remove the team member.", { type: "error" });
    } finally {
      setPendingDelete(null);
    }
  };

  const columns = [
    { key: "name", header: "Name", render: (row) => `${row.first_name ?? ""} ${row.last_name ?? ""}`.trim() || row.username },
    { key: "username", header: "Username" },
    { key: "phone", header: "Phone" },
    { key: "email", header: "Email" },
    { key: "role", header: "Role", render: (row) => <Badge>{row.role}</Badge> },
    {
      key: "is_active",
      header: "Status",
      render: (row) => <Badge color={row.is_active ? "emerald" : "white"}>{row.is_active ? "Active" : "Pending"}</Badge>,
    },
  ];

  return (
    <div>
      <PageHeader
        title="Team"
        subtitle="People you share the system with"
        actions={
          <Button
            leftIcon={<Plus className="h-4 w-4" />}
            onClick={() => {
              setActive(null);
              setIsFormOpen(true);
            }}
          >
            Add team member
          </Button>
        }
      />

      <ResponsiveTable
        columns={columns}
        rows={members}
        isLoading={isLoading}
        rowActions={(row) => (
          <Dropdown
            items={[
              {
                label: "Edit",
                icon: <Pencil className="h-4 w-4" />,
                onClick: () => {
                  // row.permissions is the array shape [{module, can_view, can_edit}],
                  // but PermissionMatrix/TeamMemberForm expect an object keyed by module.
                  const permissions = Object.fromEntries(
                    (row.permissions ?? []).map((p) => [p.module, { can_view: p.can_view, can_edit: p.can_edit }])
                  );
                  const property_ids = Array.isArray(row.property_access) ? row.property_access : [];
                  setActive({ ...row, permissions, property_ids });
                  setIsFormOpen(true);
                },
              },
              { label: "Delete", icon: <Trash2 className="h-4 w-4" />, danger: true, onClick: () => setPendingDelete(row) },
            ]}
          />
        )}
      />

      <Modal isOpen={isFormOpen} onClose={() => setIsFormOpen(false)} title={active ? "Edit team member" : "Add team member"} size="lg">
        <TeamMemberForm
          initialValues={active}
          properties={properties}
          onSubmit={handleSubmit}
          onCancel={() => setIsFormOpen(false)}
          isSubmitting={isCreating || isUpdating}
        />
      </Modal>

      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        onConfirm={handleDelete}
        title="Remove team member?"
        description={`"${pendingDelete?.username}" will lose access immediately.`}
      />
    </div>
  );
}
