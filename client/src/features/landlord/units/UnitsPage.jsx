import { useState } from "react";
import { Plus, Building2, DoorOpen, AlertCircle, Pencil, Trash2 } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import SearchInput from "@/components/ui/SearchInput";
import SummaryCard from "@/components/ui/SummaryCard";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import ResponsiveTable from "@/components/tables/ResponsiveTable";
import Dropdown from "@/components/ui/Dropdown";
import Modal from "@/components/ui/Modal";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import Button from "@/components/ui/Button";
import Badge from "@/components/ui/Badge";
import { toast } from "@/components/ui/Toast";
import UnitForm from "./UnitForm";
import { useGetUnitsQuery, useCreateUnitMutation, useUpdateUnitMutation, useDeleteUnitMutation } from "./unitApiSlice";
import { useGetPropertiesQuery } from "../properties/propertyApiSlice";
import { formatCurrency } from "@/utils/currencyFormatter";
import { toRows, toPaginationMeta, readSummary } from "@/utils/tableAdapters";
import { usePagination } from "@/hooks/usePagination";
import Pagination from "@/components/ui/Pagination";
import { ANCHORS } from "@/features/landlord/tutorials/anchors";

export default function UnitsPage() {
  const pg = usePagination();
  const [search, setSearch] = useState("");
  const { data, isLoading } = useGetUnitsQuery({ ...pg.params, search });
  const { data: propertiesData } = useGetPropertiesQuery();
  const [createUnit, { isLoading: isCreating }] = useCreateUnitMutation();
  const [updateUnit, { isLoading: isUpdating }] = useUpdateUnitMutation();
  const [deleteUnit] = useDeleteUnitMutation();

  const [activeUnit, setActiveUnit] = useState(null);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);

  const units = toRows(data);
  const meta = toPaginationMeta(data);
  const properties = toRows(propertiesData);
  // Whole-dataset figures, from the server's `summary` block — and all three
  // from the UNITS response, so they describe the same set.
  //
  // `properties` used to count the rows of an unpaginated properties query,
  // which returns page one, so this card read 20 on an account with 100
  // properties. Taking it from the properties summary fixed the count but not
  // the disagreement: search the units for one block and this card still said
  // "2 properties" beside "8 units" that were all in one of them.
  const totals = {
    properties: readSummary(data, "total_properties"),
    units: readSummary(data, "total_units"),
    vacancies: readSummary(data, "total_vacancies"),
  };

  const openCreate = () => {
    setActiveUnit(null);
    setIsFormOpen(true);
  };
  const openEdit = (unit) => {
    setActiveUnit(unit);
    setIsFormOpen(true);
  };

  const handleSubmit = async (values) => {
    try {
      if (activeUnit) {
        await updateUnit({ id: activeUnit.id, ...values }).unwrap();
        toast("Unit updated.", { type: "success" });
      } else {
        await createUnit(values).unwrap();
        toast("Unit added.", { type: "success" });
      }
      setIsFormOpen(false);
    } catch {
      toast("Could not save the unit.", { type: "error" });
    }
  };

  const handleDelete = async () => {
    try {
      await deleteUnit(pendingDelete.id).unwrap();
      toast("Unit deleted.", { type: "success" });
    } catch {
      toast("Could not delete the unit.", { type: "error" });
    } finally {
      setPendingDelete(null);
    }
  };

  const columns = [
    { key: "property", header: "Property", render: (row) => row.property_name ?? row.property?.name },
    { key: "name", header: "Unit" },
    {
      key: "occupied",
      header: "Occupied",
      render: (row) => <Badge color={row.is_occupied ? "emerald" : "white"}>{row.is_occupied ? "Yes" : "No"}</Badge>,
    },
    { key: "rent_amount", header: "Rent / month", render: (row) => formatCurrency(row.rent_amount) },
    { key: "tax_rate", header: "Tax rate", render: (row) => (row.tax_rate != null ? `${row.tax_rate}%` : "—") },
  ];

  return (
    <div>
      <PageHeader
        title="Units"
        subtitle="Every unit across your properties"
        actions={
          <Button data-tour={ANCHORS.units.addButton} leftIcon={<Plus className="h-4 w-4" />} onClick={openCreate}>
            Add unit
          </Button>
        }
      />

      {/* Server-side search. At this scale filtering the twenty rows already
          on screen would be worse than useless — it would look like it worked
          and quietly miss everything on the other pages. */}
      <SearchInput
        value={search}
        onSearch={(term) => { setSearch(term); pg.reset(); }}
        placeholder="Search unit, pay code or property…"
        aria-label="Search units"
        resultCount={meta.total}
      />

      {isLoading ? (
        <SkeletonStatCards count={3} />
      ) : (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
          <SummaryCard label="Properties" value={totals.properties} icon={<Building2 className="h-5 w-5" />} />
          <SummaryCard label="Total units" value={totals.units} icon={<DoorOpen className="h-5 w-5" />} accent="third" />
          <SummaryCard label="Vacancies" value={totals.vacancies} icon={<AlertCircle className="h-5 w-5" />} />
        </div>
      )}

      <div className="mt-6">
        <ResponsiveTable
          columns={columns}
          rows={units}
          isLoading={isLoading}
          rowActions={(row) => (
            <Dropdown
              items={[
                { label: "Edit", icon: <Pencil className="h-4 w-4" />, onClick: () => openEdit(row) },
                { label: "Delete", icon: <Trash2 className="h-4 w-4" />, danger: true, onClick: () => setPendingDelete(row) },
              ]}
            />
          )}
        />
        <Pagination page={pg.page} perPage={pg.perPage} total={meta.total} onPageChange={pg.setPage} onPerPageChange={pg.setPerPage} />
      </div>

      <Modal isOpen={isFormOpen} onClose={() => setIsFormOpen(false)} title={activeUnit ? "Edit unit" : "Add unit"}>
        <UnitForm initialValues={activeUnit} properties={properties} onSubmit={handleSubmit} onCancel={() => setIsFormOpen(false)} isSubmitting={isCreating || isUpdating} />
      </Modal>

      <ConfirmDialog
        isOpen={Boolean(pendingDelete)}
        onClose={() => setPendingDelete(null)}
        onConfirm={handleDelete}
        title="Delete unit?"
        description={`"${pendingDelete?.name}" will be soft-deleted.`}
      />
    </div>
  );
}
