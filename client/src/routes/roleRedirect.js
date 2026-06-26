import { USER_ROLES } from "@/utils/constants";
import { LANDLORD_ROUTES, TEAM_ROUTES, TENANT_ROUTES, ADMIN_ROUTES, PUBLIC_ROUTES } from "@/config/routePaths";

// After login (or when ProtectedRoutes blocks a role mismatch), send the user to their portal home.
export function roleHomePath(role) {
  switch (role) {
    case USER_ROLES.SYSTEM_ADMIN:
      return ADMIN_ROUTES.dashboard;
    case USER_ROLES.LANDLORD:
    case USER_ROLES.PROPERTY_MANAGER:
      return LANDLORD_ROUTES.dashboard;
    case USER_ROLES.TEAM_MEMBER:
      return TEAM_ROUTES.dashboard;
    case USER_ROLES.TENANT:
      return TENANT_ROUTES.dashboard;
    default:
      return PUBLIC_ROUTES.home;
  }
}

export default roleHomePath;
