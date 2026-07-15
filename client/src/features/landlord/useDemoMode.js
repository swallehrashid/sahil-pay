import { useNavigate } from "react-router-dom";
import { useDispatch } from "react-redux";
import { apiSlice } from "@/store/apiSlice";
import { getDemoMode, setDemoMode, clearDemoMode } from "@/utils/demoStorage";
import { LANDLORD_ROUTES } from "@/config/routePaths";
import { toast } from "@/components/ui/Toast";
import { useEnterDemoMutation, useExitDemoMutation, useResetDemoMutation } from "./demoApiSlice";

// Shared enter/exit/reset logic for demo mode (DEMO_MODE_SPEC.md §5.3) — used
// by both the sidebar toggle and the Settings → General card so the two entry
// points never drift out of sync.
export function useDemoMode() {
  const navigate = useNavigate();
  const dispatch = useDispatch();
  const [enterDemoMutation, { isLoading: isEntering }] = useEnterDemoMutation();
  const [exitDemoMutation, { isLoading: isExiting }] = useExitDemoMutation();
  const [resetDemoMutation, { isLoading: isResetting }] = useResetDemoMutation();

  const isActive = Boolean(getDemoMode()?.active);

  // Every demo-mode transition must reset the RTK Query cache — otherwise a
  // page could keep showing the real account's cached data after entering
  // demo, or vice versa on exit (same reason AdminImpersonationBanner does it).
  const resetCache = () => dispatch(apiSlice.util.resetApiState());

  const enter = async () => {
    try {
      await enterDemoMutation().unwrap();
      setDemoMode({ active: true });
      resetCache();
      navigate(LANDLORD_ROUTES.dashboard, { replace: true });
    } catch {
      toast("Could not start demo mode. Please try again.", { type: "error" });
    }
  };

  const exit = async () => {
    try {
      await exitDemoMutation().unwrap();
    } catch {
      // Exiting must never leave a landlord stuck in demo mode — clear
      // local state regardless of whether the audit call succeeded.
    }
    clearDemoMode();
    resetCache();
    navigate(LANDLORD_ROUTES.dashboard, { replace: true });
  };

  const reset = async () => {
    try {
      await resetDemoMutation().unwrap();
      resetCache();
      toast("Demo data has been reset.", { type: "success" });
    } catch {
      toast("Could not reset demo data.", { type: "error" });
    }
  };

  return { isActive, enter, exit, reset, isEntering, isExiting, isResetting };
}

export default useDemoMode;
