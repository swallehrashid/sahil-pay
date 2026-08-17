import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { AlertTriangle, ArrowLeft, Copy, ImagePlus, RefreshCw, Trash2 } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Select from "@/components/ui/Select";
import Checkbox from "@/components/ui/Checkbox";
import Textarea from "@/components/ui/Textarea";
import Badge from "@/components/ui/Badge";
import { SkeletonForm } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { ADMIN_ROUTES } from "@/config/routePaths";
import {
  useGetAdminArticleQuery,
  useGetAdminCategoriesQuery,
  useUpdateArticleMutation,
  usePreviewArticleMutation,
  useUploadImageMutation,
  useReplaceImageMutation,
  useUpdateImageMutation,
  useDeleteImageMutation,
} from "./adminTutorialApiSlice";

// SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md §5.1 — the markdown article editor.
//
// The preview is rendered SERVER-side by the same sanitising pipeline the
// reader side uses, so what Swalleh sees here is exactly what a landlord gets
// — including the raw-HTML escaping. Rendering markdown locally would let the
// two drift apart, which is how a preview quietly starts lying.
//
// Mobile-first: editor and preview stack vertically on a phone and only go
// side-by-side from lg up, where there's genuinely room for two columns.

// Audience labels, mirroring services/tutorial_service.VALID_ROLES. The last
// four are team-member PRESETS, not sign-in roles — everyone in that group logs
// in as a team member, and the server maps them onto their preset label. Leaving
// every box unticked means "everyone".
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

export default function AdminHelpArticleEditor() {
  const { id } = useParams();
  const { data: article, isLoading } = useGetAdminArticleQuery(id);
  const { data: categories } = useGetAdminCategoriesQuery();

  const [updateArticle, { isLoading: saving }] = useUpdateArticleMutation();
  const [preview] = usePreviewArticleMutation();
  const [uploadImage, { isLoading: uploading }] = useUploadImageMutation();
  const [replaceImage] = useReplaceImageMutation();
  const [updateImage] = useUpdateImageMutation();
  const [deleteImage] = useDeleteImageMutation();

  const [form, setForm] = useState(null);
  const [previewHtml, setPreviewHtml] = useState("");
  const bodyRef = useRef(null);
  const uploadRef = useRef(null);
  const replaceRef = useRef(null);
  const [replaceTarget, setReplaceTarget] = useState(null);

  useEffect(() => {
    if (article && !form) {
      setForm({
        title: article.title,
        slug: article.slug,
        summary: article.summary ?? "",
        category_id: article.category_id,
        body_markdown: article.body_markdown ?? "",
        // null means "inherit the category's audience" — a real, distinct state
        // from "nobody", so it round-trips rather than collapsing to [].
        visible_to_roles: article.visible_to_roles,
        is_published: article.is_published,
      });
      setPreviewHtml(article.body_html ?? "");
    }
  }, [article, form]);

  // Debounced server-side preview.
  useEffect(() => {
    if (!form) return;
    const timer = setTimeout(async () => {
      try {
        const result = await preview(form.body_markdown).unwrap();
        setPreviewHtml(result.body_html ?? "");
      } catch {
        /* a failed preview must never block typing */
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [form?.body_markdown, preview]);

  if (isLoading || !form) return <SkeletonForm fields={8} />;

  const set = (patch) => setForm((f) => ({ ...f, ...patch }));

  const save = async (publishOverride) => {
    try {
      const payload = { id, ...form };
      if (publishOverride !== undefined) payload.is_published = publishOverride;
      await updateArticle(payload).unwrap();
      if (publishOverride !== undefined) set({ is_published: publishOverride });
      toast(
        publishOverride === true ? "Published."
          : publishOverride === false ? "Unpublished — now a draft."
          : "Draft saved.",
        { type: "success" }
      );
    } catch (err) {
      toast(err?.data?.error || "Could not save the article.", { type: "error" });
    }
  };

  /** Insert markdown at the cursor, so an uploaded image lands where they were typing. */
  const insertAtCursor = (snippet) => {
    const el = bodyRef.current;
    const body = form.body_markdown ?? "";
    if (!el) {
      set({ body_markdown: `${body}\n\n${snippet}\n` });
      return;
    }
    const start = el.selectionStart ?? body.length;
    const end = el.selectionEnd ?? body.length;
    set({ body_markdown: `${body.slice(0, start)}${snippet}${body.slice(end)}` });
  };

  const handleUpload = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    formData.append("article_id", id);
    try {
      const image = await uploadImage(formData).unwrap();
      insertAtCursor(image.markdown);
      toast("Image uploaded and inserted.", { type: "success" });
    } catch (err) {
      toast(err?.data?.error || "Could not upload that image.", { type: "error" });
    }
  };

  const handleReplace = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !replaceTarget) return;
    const formData = new FormData();
    formData.append("file", file);
    try {
      await replaceImage({ id: replaceTarget, formData }).unwrap();
      toast("Image replaced — published articles update instantly.", { type: "success" });
    } catch (err) {
      toast(err?.data?.error || "Could not replace that image.", { type: "error" });
    } finally {
      setReplaceTarget(null);
    }
  };

  const roles = form.visible_to_roles ?? [];
  const toggleRole = (role) =>
    set({
      visible_to_roles: roles.includes(role)
        ? roles.filter((r) => r !== role)
        : [...roles, role],
    });

  return (
    <div className="space-y-6">
      <Link to={ADMIN_ROUTES.helpContent}
            className="inline-flex items-center gap-1 text-sm text-white/50 hover:text-white">
        <ArrowLeft size={14} /> Help Content
      </Link>

      <PageHeader
        title={form.title || "Untitled"}
        subtitle={article.updated_by ? `Last updated by ${article.updated_by}` : undefined}
      />

      {/* A published article inside a draft category reaches nobody, and the
          "Published" badge alone reads as success. Say so here, where the
          publish button is, instead of letting it be discovered by a reader
          who never sees the page. */}
      {article.is_published && article.is_reachable === false && (
        <div className="glass flex items-start gap-3 border-l-4 border-amber-400/70 p-4 text-sm text-white/80">
          <AlertTriangle size={18} className="mt-0.5 flex-shrink-0 text-amber-400" />
          <span>{article.blocked_hint}</span>
        </div>
      )}

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <Badge color={form.is_published ? "third" : "white"}>
          {form.is_published ? "Published" : "Draft"}
        </Badge>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Button type="button" variant="ghost" onClick={() => save()} isLoading={saving}>
            Save draft
          </Button>
          {form.is_published ? (
            <Button type="button" variant="ghost" onClick={() => save(false)}>
              Unpublish
            </Button>
          ) : (
            <Button type="button" onClick={() => save(true)}>Publish</Button>
          )}
        </div>
      </div>

      {/* Metadata */}
      <div className="glass space-y-4 p-5 sm:p-6">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Input label="Title" value={form.title}
                 onChange={(e) => set({ title: e.target.value })} />
          <Input label="Slug" value={form.slug}
                 hint="Links point here — changing it breaks existing links."
                 onChange={(e) => set({ slug: e.target.value })} />
          <Select
            label="Category"
            value={form.category_id}
            onChange={(e) => set({ category_id: Number(e.target.value) })}
            options={(categories ?? []).map((c) => ({ value: c.id, label: c.name }))}
          />
          <Input label="Summary" value={form.summary}
                 onChange={(e) => set({ summary: e.target.value })} />
        </div>

        <div>
          <p className="mb-2 text-sm font-medium text-white/70">Visible to</p>
          <p className="mb-2 text-xs text-white/40">
            Leave clear to inherit the category&apos;s audience.
          </p>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {ROLES.map(([role, label]) => (
              <Checkbox key={role} label={label} checked={roles.includes(role)}
                        onChange={() => toggleRole(role)} />
            ))}
          </div>
        </div>
      </div>

      {/* Editor + preview: stacked on a phone, side by side from lg up. */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="glass space-y-3 p-5 sm:p-6">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <h3 className="text-sm font-medium text-white">Markdown</h3>
            <Button type="button" variant="ghost" isLoading={uploading}
                    onClick={() => uploadRef.current?.click()}>
              <ImagePlus size={14} className="mr-1" /> Upload image
            </Button>
            <input ref={uploadRef} type="file" accept="image/*" className="hidden"
                   onChange={handleUpload} />
          </div>
          <Textarea
            ref={bodyRef}
            value={form.body_markdown}
            rows={22}
            className="font-mono text-xs"
            onChange={(e) => set({ body_markdown: e.target.value })}
          />
        </div>

        <div className="glass space-y-3 p-5 sm:p-6">
          <h3 className="text-sm font-medium text-white">Preview</h3>
          <article className="prose prose-invert max-w-none text-sm"
                   dangerouslySetInnerHTML={{ __html: previewHtml }} />
          <p className="border-t border-white/10 pt-3 text-xs text-white/30">
            Educational guidance only — not tax advice. Confirm specifics with KRA
            or a tax professional.
          </p>
        </div>
      </div>

      {/* Images */}
      <div className="glass space-y-4 p-5 sm:p-6">
        <h3 className="text-sm font-medium text-white">Images in this article</h3>
        <input ref={replaceRef} type="file" accept="image/*" className="hidden"
               onChange={handleReplace} />

        {!article.images?.length ? (
          <p className="text-sm text-white/40">
            No images yet. Upload one above and its markdown is inserted at your cursor.
          </p>
        ) : (
          <div className="space-y-3">
            {article.images.map((image) => (
              <div key={image.id}
                   className="flex flex-col gap-3 rounded-lg border border-white/10 p-3 sm:flex-row">
                <img src={image.url} alt={image.alt_text || ""}
                     className="h-24 w-full rounded object-cover sm:w-32" />
                <div className="min-w-0 flex-1 space-y-2">
                  <Input label="Caption" value={image.caption ?? ""}
                         onChange={(e) => updateImage({ id: image.id, caption: e.target.value })} />
                  <Input label="Alt text" value={image.alt_text ?? ""}
                         onChange={(e) => updateImage({ id: image.id, alt_text: e.target.value })} />
                  <div className="flex flex-col gap-2 sm:flex-row">
                    <Button type="button" variant="ghost"
                            onClick={() => { navigator.clipboard.writeText(image.markdown); toast("Markdown copied.", { type: "success" }); }}>
                      <Copy size={14} className="mr-1" /> Copy markdown
                    </Button>
                    <Button type="button" variant="ghost"
                            onClick={() => { setReplaceTarget(image.id); replaceRef.current?.click(); }}>
                      <RefreshCw size={14} className="mr-1" /> Replace
                    </Button>
                    <Button type="button" variant="ghost"
                            onClick={() => deleteImage(image.id)}>
                      <Trash2 size={14} className="mr-1" /> Delete
                    </Button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
