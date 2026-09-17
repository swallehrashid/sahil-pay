import { Link } from "react-router-dom";
import { ScrollText, ChevronRight, PenLine, Clock, CheckCircle2, AlertTriangle } from "lucide-react";
import clsx from "clsx";
import PageHeader from "@/components/layout/PageHeader";
import EmptyState from "@/components/ui/EmptyState";
import { SkeletonStatCards } from "@/components/ui/Skeleton";
import { formatDate } from "@/utils/dateFormatter";
import { TENANT_ROUTES } from "@/config/routePaths";
import { useGetPortalLeasesQuery } from "@/features/landlord/leases/leaseApiSlice";

// Every tenancy agreement this person holds — one per house or unit, across
// every landlord they rent from. Anything waiting on them sits at the top with
// a clear "Sign now"; nothing here is hidden behind a unit switcher.

const LEASE_STATUS = {
  sent:      { label: "Action needed — sign", tone: "action", icon: PenLine },
  rejected:  { label: "Returned — please correct", tone: "danger", icon: AlertTriangle },
  submitted: { label: "With your landlord for review", tone: "waiting", icon: Clock },
  approved:  { label: "Approved — download", tone: "done", icon: CheckCircle2 },
  uploaded:  { label: "Signed in person — download", tone: "done", icon: CheckCircle2 },
};

const TONE = {
  action: "border-secondary/60 bg-secondary/10 text-secondary-100",
  danger: "border-red-400/50 bg-red-500/10 text-red-200",
  waiting: "border-amber-400/40 bg-amber-500/10 text-amber-200",
  done: "border-emerald-400/40 bg-emerald-500/10 text-emerald-200",
};

export default function TenantLeases() {
  const { data, isLoading } = useGetPortalLeasesQuery();
  const items = data?.items ?? [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="My leases"
        subtitle="Read, sign and download your tenancy agreements"
      />

      {isLoading ? (
        <SkeletonStatCards count={2} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={<ScrollText className="h-6 w-6" />}
          title="No lease agreements yet"
          description="When your landlord sends you a tenancy agreement, it appears here and you'll get a notification. You can sign it here or on paper."
        />
      ) : (
        <>
          {data.action_needed > 0 && (
            <div className="glass flex items-start gap-3 border-l-4 border-secondary p-4" role="status">
              <PenLine className="mt-0.5 h-5 w-5 flex-shrink-0 text-secondary" />
              <p className="text-sm text-white">
                {data.action_needed === 1
                  ? "You have 1 lease waiting for your signature."
                  : `You have ${data.action_needed} leases waiting for your signature.`}
              </p>
            </div>
          )}

          <ul className="grid gap-3 md:grid-cols-2 2xl:grid-cols-3" data-testid="tenant-lease-list">
            {items.map((lease) => {
              const meta = LEASE_STATUS[lease.status] ?? { label: lease.status, tone: "waiting", icon: Clock };
              const Icon = meta.icon;
              return (
                <li key={lease.id}>
                  <Link
                    to={`${TENANT_ROUTES.leases}/${lease.id}`}
                    className="glass group flex h-full flex-col gap-3 p-4 transition-colors hover:border-secondary/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-secondary sm:p-5"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-base font-medium text-white">{lease.title}</p>
                        <p className="mt-0.5 truncate text-sm text-white/55">
                          {[lease.unit_name && `Unit ${lease.unit_name}`, lease.property_name]
                            .filter(Boolean).join(" · ")}
                        </p>
                        <p className="truncate text-xs text-white/40">{lease.landlord_name}</p>
                      </div>
                      <ChevronRight className="mt-1 h-5 w-5 flex-shrink-0 text-white/30 transition-transform group-hover:translate-x-0.5" />
                    </div>
                    <span className={clsx("inline-flex w-fit items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium", TONE[meta.tone])}>
                      <Icon className="h-3.5 w-3.5" /> {meta.label}
                    </span>
                    <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-white/50">
                      <dt>Sent</dt><dd className="text-right text-white/75">{lease.sent_at ? formatDate(lease.sent_at) : "—"}</dd>
                      <dt>Signed</dt><dd className="text-right text-white/75">{lease.signed_at ? formatDate(lease.signed_at) : "—"}</dd>
                      {lease.reviewed_at && lease.status === "approved" && (
                        <><dt>Approved</dt><dd className="text-right text-white/75">{formatDate(lease.reviewed_at)}</dd></>
                      )}
                    </dl>
                  </Link>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
