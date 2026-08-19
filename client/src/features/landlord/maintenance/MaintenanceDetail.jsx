import { useState } from "react";
import { ExternalLink, ImageOff, Loader2, Lock } from "lucide-react";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import Checkbox from "@/components/ui/Checkbox";
import Textarea from "@/components/ui/Textarea";
import StatusBadge from "@/components/ui/StatusBadge";
import { toast } from "@/components/ui/Toast";
import { formatDate } from "@/utils/dateFormatter";
import { MAINTENANCE_STATUSES } from "@/utils/constants";
import { usePermissions } from "@/hooks/usePermissions";
import {
  useUpdateMaintenanceRequestMutation,
  useGetMaintenanceCommentsQuery,
  useAddMaintenanceCommentMutation,
} from "./maintenanceApiSlice";

// The photo a tenant attaches is the whole point of the report — "the tap is
// leaking" and a picture of the ceiling below it are very different jobs. The
// API has always returned `image_url`, but nothing in the portal ever rendered
// it, so from the office side the request arrived as text with no way to see
// what had been sent. This screen is where that photo shows up, and where the
// status moves without going through the full edit form.

// models.MaintenanceStatus: open -> in_progress -> closed. The primary button
// offers the next step so the common path is one click; every other status
// stays available below it.
const NEXT_STATUS = {
  open: "in_progress",
  in_progress: "closed",
};

const STATUS_ACTION_LABEL = {
  in_progress: "Start work",
  closed: "Mark closed",
};

function Field({ label, children }) {
  if (children === null || children === undefined || children === "") return null;
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-white/40">{label}</dt>
      <dd className="mt-0.5 text-sm text-white/85">{children}</dd>
    </div>
  );
}

export default function MaintenanceDetail({ request, onClose }) {
  const { can } = usePermissions();
  const canEdit = can("maintenance", "edit");
  const [updateRequest, { isLoading: isSaving }] = useUpdateMaintenanceRequestMutation();
  const [imageFailed, setImageFailed] = useState(false);

  if (!request) return null;

  const nextStatus = NEXT_STATUS[request.status];

  const setStatus = async (status) => {
    try {
      await updateRequest({ id: request.id, body: { status } }).unwrap();
      toast(`Marked ${status.replace("_", " ")}.`, { type: "success" });
    } catch {
      toast("Could not update the status.", { type: "error" });
    }
  };

  return (
    <Modal isOpen onClose={onClose} title={request.summary} size="lg">
      <div className="space-y-5">
        <div className="flex flex-wrap items-center gap-3">
          <StatusBadge status={request.status} />
          <span className="text-xs text-white/40">
            Reported {formatDate(request.created_at)}
          </span>
        </div>

        <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Property">{request.property_name}</Field>
          <Field label="Unit">{request.unit_name}</Field>
          <Field label="Category">{request.category}</Field>
          <Field label="Reported by">{request.tenant_name}</Field>
        </dl>

        {request.description && (
          <div>
            <dt className="text-xs uppercase tracking-wide text-white/40">Description</dt>
            {/* whitespace-pre-line: tenants type these on a phone and use line
                breaks to separate points. Collapsing them loses the structure. */}
            <dd className="mt-1 whitespace-pre-line text-sm leading-relaxed text-white/85">
              {request.description}
            </dd>
          </div>
        )}

        <div>
          <dt className="mb-2 text-xs uppercase tracking-wide text-white/40">Photo</dt>
          {request.image_url && !imageFailed ? (
            <div className="space-y-2">
              {/* Opens full size in a new tab: the in-page copy is capped so the
                  dialog stays usable, but a plumber wants to zoom in. */}
              <a href={request.image_url} target="_blank" rel="noopener noreferrer">
                <img
                  src={request.image_url}
                  alt={`Photo attached to: ${request.summary}`}
                  onError={() => setImageFailed(true)}
                  className="max-h-80 w-auto rounded-xl border border-white/10 object-contain"
                />
              </a>
              <a
                href={request.image_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-secondary hover:underline"
              >
                <ExternalLink className="h-3 w-3" /> Open full size
              </a>
            </div>
          ) : (
            <p className="flex items-center gap-2 text-sm text-white/40">
              <ImageOff className="h-4 w-4" />
              {request.image_url
                ? "The attached photo could not be loaded."
                : "No photo was attached to this request."}
            </p>
          )}
        </div>

        {canEdit && (
          <div className="flex flex-wrap items-center gap-2 border-t border-white/10 pt-4">
            {nextStatus && (
              <Button onClick={() => setStatus(nextStatus)} isLoading={isSaving}>
                {isSaving && <Loader2 className="mr-1 h-4 w-4 animate-spin" />}
                {STATUS_ACTION_LABEL[nextStatus]}
              </Button>
            )}
            {/* Every other status stays reachable — work does not always move
                forwards, and a request reopened after a bad repair is common. */}
            {MAINTENANCE_STATUSES.filter((s) => s !== request.status && s !== nextStatus).map((s) => (
              <Button key={s} variant="ghost" onClick={() => setStatus(s)} disabled={isSaving}>
                {s.replace("_", " ")}
              </Button>
            ))}
          </div>
        )}

        <CommentThread requestId={request.id} canEdit={canEdit} />
      </div>
    </Modal>
  );
}

/**
 * The running conversation about a job.
 *
 * "Internal note" is opt-in rather than the default: the common case is telling
 * the tenant what is happening, and defaulting to internal would quietly hide
 * updates from the one person waiting for them.
 */
function CommentThread({ requestId, canEdit }) {
  const { data, isLoading } = useGetMaintenanceCommentsQuery(requestId);
  const [addComment, { isLoading: isPosting }] = useAddMaintenanceCommentMutation();
  const [body, setBody] = useState("");
  const [isInternal, setIsInternal] = useState(false);

  const comments = data?.comments ?? [];

  const post = async () => {
    const text = body.trim();
    if (!text) return;
    try {
      await addComment({ id: requestId, body: text, is_internal: isInternal }).unwrap();
      setBody("");
      setIsInternal(false);
    } catch {
      toast("Could not add the note.", { type: "error" });
    }
  };

  return (
    <div className="border-t border-white/10 pt-4">
      <h3 className="mb-3 text-xs uppercase tracking-wide text-white/40">Notes</h3>

      {isLoading ? (
        <p className="text-sm text-white/40">Loading notes…</p>
      ) : comments.length === 0 ? (
        <p className="text-sm text-white/40">No notes yet.</p>
      ) : (
        <ul className="space-y-3">
          {comments.map((c) => (
            <li
              key={c.id}
              className={
                c.is_internal
                  ? "rounded-lg border-l-2 border-amber-400/60 bg-amber-400/5 px-3 py-2"
                  : "rounded-lg bg-white/5 px-3 py-2"
              }
            >
              <div className="flex flex-wrap items-center gap-2 text-xs text-white/45">
                <span className="text-white/70">{c.author_name || c.author_role}</span>
                <span>{formatDate(c.created_at)}</span>
                {c.is_internal && (
                  <span className="flex items-center gap-1 text-amber-300/80">
                    <Lock className="h-3 w-3" /> internal — not shown to the tenant
                  </span>
                )}
              </div>
              <p className="mt-1 whitespace-pre-line text-sm text-white/85">{c.body}</p>
            </li>
          ))}
        </ul>
      )}

      {canEdit && (
        <div className="mt-4 space-y-2">
          <Textarea
            label="Add a note"
            rows={2}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="e.g. Plumber booked for Tuesday morning."
          />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Checkbox
              label="Internal note — hide from the tenant"
              checked={isInternal}
              onChange={(e) => setIsInternal(e.target.checked)}
            />
            <Button onClick={post} isLoading={isPosting} disabled={!body.trim()}>
              Add note
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
