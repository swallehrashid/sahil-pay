import { useLocation } from "react-router-dom";
import { LANDLORD_ROUTES, TEAM_ROUTES } from "@/config/routePaths";

// The route table for the portal the page is mounted in. The landlord module
// pages are re-mounted under /team for team members, so a link built from
// LANDLORD_ROUTES there sends the member to a portal they cannot enter.
export function usePortalRoutes() {
  const { pathname } = useLocation();
  return pathname.startsWith("/team") ? TEAM_ROUTES : LANDLORD_ROUTES;
}

export default usePortalRoutes;
