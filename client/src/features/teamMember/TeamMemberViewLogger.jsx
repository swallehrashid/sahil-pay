import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import { useLogViewMutation } from "./teamMemberApiSlice";

// Maps a team member's current /team/* path to a "meaningful view" audit entry.
// Only real navigation to a permission-gated module page (or a specific record's
// detail view) is described here — the dashboard, own-profile and notifications
// pages carry no `module` and are intentionally NOT logged, and background
// polling / dropdown fetches never reach this file at all.
//
// Returns null for a path we don't want to log.
function describe(pathname) {
  // /team/<...> — strip the portal prefix.
  const rest = pathname.replace(/^\/team\/?/, "");
  const parts = rest.split("/").filter(Boolean);
  if (parts.length === 0) return null;

  const [a, b, c] = parts;

  switch (a) {
    case "invoices":
      return { module: "invoices", label: "Viewed Invoices" };
    case "payments":
      if (b === "bank-statement" && c)
        return { module: "payments", label: `Viewed bank statement review #${c}`, entity_type: "payment", entity_id: Number(c) };
      return { module: "payments", label: "Viewed Payments" };
    case "tenants":
      if (b === "deleted") return { module: "tenants", label: "Viewed Deleted Tenants" };
      if (b && c === "transactions")
        return { module: "tenants", label: `Viewed tenant #${b} transactions`, entity_type: "tenant", entity_id: Number(b) };
      return { module: "tenants", label: "Viewed Tenants" };
    case "properties":
      return { module: "properties", label: "Viewed Properties" };
    case "units":
      return { module: "units", label: "Viewed Units" };
    case "utilities":
      return { module: "utilities", label: "Viewed Utilities" };
    case "expenses":
      return { module: "expenses", label: "Viewed Expenses" };
    case "maintenance":
      return { module: "maintenance", label: "Viewed Maintenance" };
    case "groups":
      return { module: "groups", label: "Viewed Property Groups" };
    case "reports":
      if (b === "insights") return { module: "reports", label: "Viewed Reports — Insights" };
      return { module: "reports", label: "Viewed Reports — Statements" };
    case "communications":
      return { module: "messages", label: "Viewed Communications" };
    // dashboard, profile, notifications → not logged
    default:
      return null;
  }
}

export default function TeamMemberViewLogger() {
  const location = useLocation();
  const [logView] = useLogViewMutation();
  const lastKey = useRef(null);

  useEffect(() => {
    const info = describe(location.pathname);
    if (!info) return;

    // Client-side guard against re-firing for the exact same target (e.g. a
    // re-render). The backend also dedupes within a 30s window as a backstop.
    const key = `${info.module}:${info.entity_type || "page"}:${info.entity_id || ""}:${info.label}`;
    if (lastKey.current === key) return;
    lastKey.current = key;

    // Fire-and-forget — never let a logging failure disrupt navigation.
    logView(info).catch(() => {});
  }, [location.pathname, logView]);

  return null;
}
