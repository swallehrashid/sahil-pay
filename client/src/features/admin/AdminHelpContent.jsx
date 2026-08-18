import { useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, ChevronUp, Plus, Trash2 } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Checkbox from "@/components/ui/Checkbox";
import Modal from "@/components/ui/Modal";
import Badge from "@/components/ui/Badge";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import EmptyState from "@/components/ui/EmptyState";
import { SkeletonForm } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { ADMIN_ROUTES } from "@/config/routePaths";
import {
  useGetAdminCategoriesQuery,
  useGetAdminArticlesQuery,
  useCreateCategoryMutation,
  useUpdateCategoryMutation,
  useReorderCategoriesMutation,
  useDeleteCategoryMutation,
  useCreateArticleMutation,
} from "./adminTutorialApiSlice";

// SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md §5.1 — the Help Content CMS.
//
// Categories with their articles, publish state, role visibility and ordering.
// Nothing here is visible to a landlord or tenant until it is PUBLISHED, and
// a category holding published articles refuses to be deleted — links already
// out in the world would 404 silently otherwise.
//
// Mobile-first: everything is a stacked card list. Reordering uses explicit
// up/down buttons rather than drag, because dragging a list item is close to
// unusable on a touch screen and impossible with a keyboard.

// Mirrors services/tutorial_service.VALID_ROLES — see AdminHelpArticleEditor for
// why the indented four are presets rather than sign-in roles.
const ROLES = [
  ["tenant", "Tenants"],
  ["landlord", "Landlords"],
  ["property_manager", "Property managers"],
  ["team_member", "Team members (all)"],
  ["caretaker", "— Caretakers"],
  ["accountant", "— Accountants"],
  ["secretary", "— Secretaries"],
  ["owner", "— Owners"],
];

const BLANK = {
  name: "", slug: "", icon: "", description: "",
  visible_to_roles: [], is_published: false,
};

function CategoryForm({ value, onChange }) {
  const roles = value.visible_to_roles ?? [];
  const toggleRole = (role) =>
    onChange({
      ...value,
      visible_to_roles: roles.includes(role)
        ? roles.filter((r) => r !== role)
        : [...roles, role],
    });

  return (
    <div className="space-y-4">
      <Input label="Name" value={value.name} required
             onChange={(e) => onChange({ ...value, name: e.target.value })} />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Input label="Slug" value={value.slug} hint="Auto-generated from the name if blank."
               onChange={(e) => onChange({ ...value, slug: e.target.value })} />
        <Input label="Icon" value={value.icon} hint="A lucide icon name, e.g. landmark."
               onChange={(e) => onChange({ ...value, icon: e.target.value })} />
      </div>
      <Input label="Description" value={value.description}
             onChange={(e) => onChange({ ...value, description: e.target.value })} />

      <div>
        <p className="mb-2 text-sm font-medium text-white/70">Visible to</p>
        <p className="mb-2 text-xs text-white/40">
          Leave every box clear to show this to all roles.
        </p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {ROLES.map(([role, label]) => (
            <Checkbox key={role} label={label} checked={roles.includes(role)}
                      onChange={() => toggleRole(role)} />
          ))}
        </div>
      </div>

      <Checkbox
        label="Published — visible to the roles above"
        checked={value.is_published}
        onChange={(e) => onChange({ ...value, is_published: e.target.checked })}
      />
    </div>
  );
}

export default function AdminHelpContent() {
  const { data: categories, isLoading } = useGetAdminCategoriesQuery();
  const { data: articles } = useGetAdminArticlesQuery();
  const [createCategory, { isLoading: creating }] = useCreateCategoryMutation();
  const [updateCategory, { isLoading: updating }] = useUpdateCategoryMutation();
  const [reorderCategories] = useReorderCategoriesMutation();
  const [deleteCategory] = useDeleteCategoryMutation();
  const [createArticle] = useCreateArticleMutation();

  const [editing, setEditing] = useState(null);   // {…category} or BLANK for new
  const [pendingDelete, setPendingDelete] = useState(null);
  const [newArticleFor, setNewArticleFor] = useState(null);
  const [newArticleTitle, setNewArticleTitle] = useState("");

  if (isLoading) return <SkeletonForm fields={6} />;

  const list = categories ?? [];
  const byCategory = (id) => (articles ?? []).filter((a) => a.category_id === id);

  const save = async () => {
    try {
      if (editing.id) {
        await updateCategory(editing).unwrap();
        toast("Category saved.", { type: "success" });
      } else {
        await createCategory(editing).unwrap();
        toast("Category created.", { type: "success" });
      }
      setEditing(null);
    } catch (err) {
      toast(err?.data?.error || "Could not save the category.", { type: "error" });
    }
  };

  const move = async (index, delta) => {
    const next = [...list];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    await reorderCategories(next.map((c) => c.id));
  };

  const confirmDelete = async () => {
    try {
      await deleteCategory(pendingDelete.id).unwrap();
      toast("Category deleted.", { type: "success" });
    } catch (err) {
      // The server refuses while published articles remain — surface its
      // wording, which names how many need unpublishing first.
      toast(err?.data?.error || "Could not delete that category.", { type: "error" });
    } finally {
      setPendingDelete(null);
    }
  };

  const addArticle = async () => {
    try {
      const article = await createArticle({
        category_id: newArticleFor.id,
        title: newArticleTitle,
      }).unwrap();
      toast("Article created as a draft.", { type: "success" });
      setNewArticleFor(null);
      setNewArticleTitle("");
      window.location.assign(ADMIN_ROUTES.helpArticleEditPath(article.id));
    } catch (err) {
      toast(err?.data?.error || "Could not create the article.", { type: "error" });
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Help Content"
        subtitle="Guides shown inside every portal. Nothing is visible until you publish it."
      />

      <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
        <Button type="button" onClick={() => setEditing({ ...BLANK })}>
          <Plus size={16} className="mr-1" /> New category
        </Button>
      </div>

      {!list.length ? (
        <EmptyState
          title="No categories yet"
          description="Create a category to start writing guides."
        />
      ) : (
        <div className="space-y-4">
          {list.map((category, index) => (
            <div key={category.id} className="glass space-y-4 p-5 sm:p-6">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-base font-medium text-white">{category.name}</h3>
                    <Badge color={category.is_published ? "third" : "white"}>
                      {category.is_published ? "Published" : "Draft"}
                    </Badge>
                  </div>
                  <p className="mt-1 text-xs text-white/40">
                    /{category.slug} · {category.published_article_count} of{" "}
                    {category.article_count} articles published
                    {category.visible_to_roles?.length
                      ? ` · ${category.visible_to_roles.join(", ")}`
                      : " · all roles"}
                  </p>
                </div>

                <div className="flex shrink-0 flex-wrap gap-2">
                  <Button type="button" variant="ghost" onClick={() => move(index, -1)}
                          disabled={index === 0} aria-label="Move up">
                    <ChevronUp size={16} />
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => move(index, 1)}
                          disabled={index === list.length - 1} aria-label="Move down">
                    <ChevronDown size={16} />
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => setEditing(category)}>
                    Edit
                  </Button>
                  <Button type="button" variant="ghost" onClick={() => setPendingDelete(category)}
                          aria-label="Delete category">
                    <Trash2 size={16} />
                  </Button>
                </div>
              </div>

              <div className="space-y-2 border-t border-white/10 pt-4">
                {byCategory(category.id).map((article) => (
                  <Link
                    key={article.id}
                    to={ADMIN_ROUTES.helpArticleEditPath(article.id)}
                    className="flex flex-col gap-1 rounded px-2 py-2 transition-colors hover:bg-white/5 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <span className="text-sm text-white/80">{article.title}</span>
                    {/* "Published" on its own is misleading when the category is
                        still a draft — the article is then invisible to every
                        reader, and the CMS used to give no hint of that. */}
                    {article.is_published && article.is_reachable === false ? (
                      <span className="flex items-center gap-1.5" title={article.blocked_hint}>
                        <Badge color="white">Published — not visible</Badge>
                      </span>
                    ) : (
                      <Badge color={article.is_published ? "third" : "white"}>
                        {article.is_published ? "Published" : "Draft"}
                      </Badge>
                    )}
                  </Link>
                ))}
                <Button type="button" variant="ghost" className="w-full sm:w-auto"
                        onClick={() => setNewArticleFor(category)}>
                  <Plus size={14} className="mr-1" /> New article
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <Modal isOpen={!!editing} onClose={() => setEditing(null)}
             title={editing?.id ? "Edit category" : "New category"} size="lg">
        {editing && (
          <div className="space-y-5">
            <CategoryForm value={editing} onChange={setEditing} />
            <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
              <Button type="button" variant="ghost" onClick={() => setEditing(null)}>
                Cancel
              </Button>
              <Button type="button" onClick={save} isLoading={creating || updating}>
                Save
              </Button>
            </div>
          </div>
        )}
      </Modal>

      <Modal isOpen={!!newArticleFor} onClose={() => setNewArticleFor(null)}
             title={`New article in ${newArticleFor?.name ?? ""}`} size="md">
        <div className="space-y-4">
          <Input label="Title" value={newArticleTitle} required
                 onChange={(e) => setNewArticleTitle(e.target.value)} />
          <p className="text-xs text-white/40">
            Created as a draft. You&apos;ll go straight to the editor.
          </p>
          <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <Button type="button" variant="ghost" onClick={() => setNewArticleFor(null)}>
              Cancel
            </Button>
            <Button type="button" onClick={addArticle} disabled={!newArticleTitle.trim()}>
              Create
            </Button>
          </div>
        </div>
      </Modal>

      <ConfirmDialog
        isOpen={!!pendingDelete}
        title="Delete this category?"
        description={`"${pendingDelete?.name}" and its draft articles will be removed. This cannot be undone.`}
        confirmLabel="Delete"
        onConfirm={confirmDelete}
        onClose={() => setPendingDelete(null)}
      />
    </div>
  );
}
