import { useState } from "react";
import { FileText, Download, AlertTriangle, CheckCircle2 } from "lucide-react";
import PageHeader from "@/components/layout/PageHeader";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import EmptyState from "@/components/ui/EmptyState";
import { SkeletonForm } from "@/components/ui/Skeleton";
import { toast } from "@/components/ui/Toast";
import { formatDate } from "@/utils/dateFormatter";
import { downloadFile } from "@/utils/downloadFile";
import {
  useGetPortalLeaseQuery,
  useSubmitPortalLeaseMutation,
} from "@/features/landlord/leases/leaseApiSlice";

// The tenant's side of a tenancy agreement: read it, sign it, keep a copy.
//
// Signing is a typed name plus an explicit tick, recorded with the time and
// where it came from. Deliberately not a drawn squiggle: on a phone that
// produces an unreadable scrawl that proves far less than a recorded consent
// event with provenance, and it is fiddly enough that people abandon it.

export default function TenantLease() {
  const { data, isLoading } = useGetPortalLeaseQuery();
  const [submit, { isLoading: isSubmitting }] = useSubmitPortalLeaseMutation();

  const [name, setName] = useState("");
  const [agreed, setAgreed] = useState(false);

  const lease = data?.lease ?? null;

  const sign = async (e) => {
    e.preventDefault();
    try {
      await submit({ signed_name: name, agreed }).unwrap();
      toast("Signed and sent to your landlord.", { type: "success" });
      setName(""); setAgreed(false);
    } catch (err) {
      toast(err?.data?.error || "Could not submit your lease.", { type: "error" });
    }
  };

  if (isLoading) return <SkeletonForm fields={6} />;

  if (!lease) {
    return (
      <div className="space-y-6">
        <PageHeader title="Tenancy agreement" />
        <EmptyState
          title="No agreement yet"
          description="When your landlord sends you a tenancy agreement, it will appear here for you to read and sign."
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Tenancy agreement"
        subtitle="Read it through, then sign at the bottom"
        actions={
          lease.is_downloadable ? (
            <Button leftIcon={<Download className="h-4 w-4" />}
                    onClick={() => downloadFile("/portal/lease/download",
                                                { filename: "tenancy-agreement.pdf" })}>
              Download my copy
            </Button>
          ) : null
        }
      />

      {lease.status === "approved" && (
        <div className="glass flex items-start gap-3 border-l-2 border-emerald-400/60 p-4">
          <CheckCircle2 className="mt-0.5 h-5 w-5 flex-shrink-0 text-emerald-300" />
          <div>
            <p className="text-sm text-white">Your agreement is approved.</p>
            <p className="mt-1 text-xs text-white/50">
              Signed by you on {formatDate(lease.signed_at)}. Keep a copy for your
              records — you can download it any time.
            </p>
          </div>
        </div>
      )}

      {lease.status === "uploaded" && (
        <div className="glass flex items-start gap-3 border-l-2 border-emerald-400/60 p-4">
          <CheckCircle2 className="mt-0.5 h-5 w-5 flex-shrink-0 text-emerald-300" />
          <p className="text-sm text-white">
            Your signed agreement is on file. You can download a copy any time.
          </p>
        </div>
      )}

      {lease.status === "submitted" && (
        <div className="glass flex items-start gap-3 border-l-2 border-amber-400/60 p-4">
          <FileText className="mt-0.5 h-5 w-5 flex-shrink-0 text-amber-200" />
          <div>
            <p className="text-sm text-white">Signed — with your landlord for review.</p>
            <p className="mt-1 text-xs text-white/50">
              You'll be able to download your copy once they approve it.
            </p>
          </div>
        </div>
      )}

      {lease.status === "rejected" && (
        <div className="glass flex items-start gap-3 border-l-2 border-red-400/60 p-4">
          <AlertTriangle className="mt-0.5 h-5 w-5 flex-shrink-0 text-red-300" />
          <div>
            <p className="text-sm text-white">Your landlord asked for a correction.</p>
            <p className="mt-1 text-sm text-white/70">{lease.rejection_reason}</p>
            <p className="mt-1 text-xs text-white/50">
              Read it through again and sign below to resubmit.
            </p>
          </div>
        </div>
      )}

      {/* The agreement itself. Sanitised server-side; scrolls inside its own
          box so a long document never drags the page sideways on a phone. */}
      {lease.body_html && (
        <article
          className="glass max-h-[60vh] overflow-y-auto p-5 text-sm leading-relaxed text-white/80
                     [&_h1]:mb-4 [&_h1]:text-base [&_h1]:font-medium [&_h1]:tracking-wide [&_h1]:text-white
                     [&_h2]:mt-5 [&_h2]:mb-1 [&_h2]:text-sm [&_h2]:font-medium [&_h2]:text-white
                     [&_p]:my-2 [&_strong]:text-white"
          dangerouslySetInnerHTML={{ __html: lease.body_html }}
        />
      )}

      {lease.can_sign ? (
        <form onSubmit={sign} className="glass space-y-4 p-5">
          <h3 className="text-base font-medium text-white">Sign</h3>
          <p className="text-sm text-white/50">
            Type your full name exactly as it appears on your ID. We record the
            date and time you agreed — that is what makes this binding.
          </p>

          <Input
            label="Your full name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Amina Wanjiru Kamau"
            required
          />

          <label className="flex cursor-pointer items-start gap-2 text-sm text-white/70">
            <input
              type="checkbox"
              checked={agreed}
              onChange={(e) => setAgreed(e.target.checked)}
              className="mt-0.5 h-4 w-4 flex-shrink-0 accent-secondary"
            />
            <span>
              I have read this tenancy agreement and I agree to be bound by it.
            </span>
          </label>

          <div className="flex justify-end">
            <Button type="submit" isLoading={isSubmitting}
                    disabled={name.trim().length < 3 || !agreed}>
              Sign and submit
            </Button>
          </div>
        </form>
      ) : (
        lease.signed_name && (
          <div className="glass p-5">
            <p className="text-xs uppercase tracking-wide text-white/40">Signed by</p>
            <p className="mt-1 font-serif text-lg italic text-white">{lease.signed_name}</p>
            <p className="mt-1 text-xs text-white/40">
              {formatDate(lease.signed_at)}
            </p>
          </div>
        )
      )}
    </div>
  );
}
