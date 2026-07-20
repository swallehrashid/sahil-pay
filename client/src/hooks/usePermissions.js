import { useMemo } from "react";
import { useAuth } from "./useAuth";
import { can, buildVisibleNav } from "@/utils/permissions";

// Drives conditional render/disable for team members. Landlords/PMs get permissions=null,
// so `can()` always resolves true and every module is treated as fully accessible.
export function usePermissions() {
  const { permissions } = useAuth();

  return useMemo(
    () => ({
      permissions,
      can: (module, level = "view") => can(permissions, module, level),
      visibleNav: (navItems) => buildVisibleNav(navItems, permissions),
    }),
    [permissions]
  );
}

export default usePermissions;
