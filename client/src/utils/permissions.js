// Centralizes the Team-Member permission-matrix logic so it is never re-implemented per page.
// `permissions` shape: { [module]: { can_view: bool, can_edit: bool } } — null/undefined means
// the caller is a landlord/PM (no gating applies).

export function can(permissions, module, level = "view") {
  if (!permissions) return true;
  const entry = permissions[module];
  if (!entry) return false;
  if (level === "edit") return Boolean(entry.can_edit);
  return Boolean(entry.can_view || entry.can_edit);
}

// A hidden module must never render in nav at all — not merely disabled.
//
// `item.requires` lets a link demand EDIT rather than view. Most nav entries
// open a list, so view is the right gate; a few open a screen whose only
// purpose is to write — Bulk import creates properties, units and tenants
// wholesale — and offering those to a view-only member is an invitation to a
// 403. The backend gates them independently either way; this stops the link
// appearing at all, which is the rule the rest of this nav already follows.
export function buildVisibleNav(navItems, permissions) {
  if (!permissions) return navItems;
  return navItems.filter(
    (item) => !item.module || can(permissions, item.module, item.requires || "view")
  );
}

export default { can, buildVisibleNav };
