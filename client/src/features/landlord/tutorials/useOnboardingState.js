import { useCallback, useMemo, useState } from "react";
import { useAuth } from "@/hooks/useAuth";
import { useGetOnboardingQuery, useUpdateOnboardingMutation } from "./tutorialsApiSlice";

const DEFAULT_COUNTS = {
  properties: 0, units: 0, tenants: 0, invoices: 0, payments: 0, charge_categories: 0,
};

// Landlord/PM only, and never while an admin is impersonating (ONBOARDING_TUTORIALS_SPEC.md
// §4.5) — the admin poking around must not consume the landlord's one-time welcome or write
// progress on their behalf.
function useIsEligible() {
  const { role, impersonating } = useAuth();
  return (role === "landlord" || role === "property_manager") && !impersonating;
}

// Team members run the same tours but have no server-side progress blob (that is
// the account owner's). Their "Completed" badges are kept on their own device.
const teamKey = (userId) => `sp_team_tutorials_${userId}`;

function readTeamProgress(userId) {
  try {
    return JSON.parse(localStorage.getItem(teamKey(userId)) || "{}");
  } catch {
    return {};
  }
}

// Reads/writes the landlord's onboarding+tutorials progress blob (ONBOARDING_TUTORIALS_SPEC.md
// §4.3). Seeds instantly from /auth/me's embedded profile.onboarding_state so the welcome-modal
// decision never has to wait on a network round trip; the live RTK Query value takes over once
// it resolves.
export function useOnboardingState() {
  const { user, role } = useAuth();
  const isEligible = useIsEligible();
  const isTeam = role === "team_member";
  const userId = user?.id;
  const [teamProgress, setTeamProgress] = useState(() => (isTeam && user?.id ? readTeamProgress(user.id) : {}));
  const seedState = user?.profile?.onboarding_state ?? null;

  const { data, isLoading, isFetching } = useGetOnboardingQuery(undefined, { skip: !isEligible });
  const [updateOnboarding] = useUpdateOnboardingMutation();

  const state = data ? data.state : seedState;
  const counts = data?.counts ?? DEFAULT_COUNTS;
  // Only true while we have neither the seed nor a resolved query — used to gate the
  // welcome modal so it never flashes before we actually know welcome_seen_at.
  const isHydrated = Boolean(data) || Boolean(seedState) || (!isLoading && !isFetching);

  const write = useCallback(
    (next) => {
      if (!isEligible) return;
      // Fire-and-forget — progress writes never surface an error toast (spec §10.7);
      // worst case a checklist tick or the welcome modal re-shows once.
      updateOnboarding(next).catch(() => {});
    },
    [isEligible, updateOnboarding]
  );

  const markWelcomeSeen = useCallback(() => {
    if (!isEligible || state?.welcome_seen_at) return;
    write({
      version: 1,
      welcome_seen_at: new Date().toISOString(),
      checklist_dismissed_at: state?.checklist_dismissed_at ?? null,
      tutorials: state?.tutorials ?? {},
    });
  }, [isEligible, state, write]);

  const dismissChecklist = useCallback(() => {
    if (!isEligible) return;
    write({
      version: 1,
      welcome_seen_at: state?.welcome_seen_at ?? new Date().toISOString(),
      checklist_dismissed_at: new Date().toISOString(),
      tutorials: state?.tutorials ?? {},
    });
  }, [isEligible, state, write]);

  const markTutorial = useCallback(
    (tutorialId, status) => {
      if (isTeam && userId) {
        const next = { ...readTeamProgress(userId), [tutorialId]: { status, at: new Date().toISOString() } };
        try {
          localStorage.setItem(teamKey(userId), JSON.stringify(next));
        } catch {
          // storage unavailable — the badge just won't persist
        }
        setTeamProgress(next);
        return;
      }
      if (!isEligible) return;
      write({
        version: 1,
        welcome_seen_at: state?.welcome_seen_at ?? null,
        checklist_dismissed_at: state?.checklist_dismissed_at ?? null,
        tutorials: {
          ...(state?.tutorials ?? {}),
          [tutorialId]: { status, at: new Date().toISOString() },
        },
      });
    },
    [isEligible, isTeam, userId, state, write]
  );

  const tutorialStatus = useCallback(
    (tutorialId) => (isTeam ? teamProgress[tutorialId]?.status : state?.tutorials?.[tutorialId]?.status) ?? null,
    [isTeam, teamProgress, state]
  );

  return useMemo(
    () => ({
      isEligible,
      // Who may start a tour at all: the account owner, or a team member.
      canRunTours: isEligible || isTeam,
      isHydrated,
      state,
      counts,
      markWelcomeSeen,
      dismissChecklist,
      markTutorial,
      tutorialStatus,
    }),
    [isEligible, isTeam, isHydrated, state, counts, markWelcomeSeen, dismissChecklist, markTutorial, tutorialStatus]
  );
}

export default useOnboardingState;
