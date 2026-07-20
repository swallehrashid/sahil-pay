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
export function buildVisibleNav(navItems, permissions) {
  if (!permissions) return navItems;
  return navItems.filter((item) => !item.module || can(permissions, item.module, "view"));
}

export default { can, buildVisibleNav };
