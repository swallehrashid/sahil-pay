import { LANDLORD_ROUTES, TEAM_ROUTES } from "@/config/routePaths";

/**
 * Make the tutorial library work in the Team Member portal.
 *
 * The tutorials were authored for the landlord and hard-code `/landlord/...`
 * routes in their steps. A team member following one would be navigated to a
 * portal they cannot enter and bounced straight home, which looks like the
 * tutorial is broken.
 *
 * Two things have to happen, and they are different questions:
 *
 *   WHICH TUTORIALS may this person see at all?  Their permission matrix. A
 *   caretaker with no `invoices` access has no use for "Create an invoice",
 *   and showing it teaches them to click things they will be refused.
 *
 *   WHICH STEPS still make sense in their portal?  Some steps drive screens
 *   that only exist for the landlord — Settings, the notification composer.
 *   Those steps are DROPPED rather than rewritten, because there is no
 *   equivalent page to point at. Everything else has a `/team/...` twin,
 *   since both portals are built from the same shared module list.
 *
 * A tutorial left with no usable steps is dropped entirely: a card that opens
 * an empty tour is worse than no card.
 */

// Every path the team portal actually serves. Both route tables are generated
// from the same SHARED_MODULES list, so membership here is the honest test of
// "does this screen exist for a team member".
const TEAM_PATHS = new Set(
  Object.values(TEAM_ROUTES).filter((value) => typeof value === "string"),
);

const LANDLORD_PREFIX = `${LANDLORD_ROUTES.root}/`;
const TEAM_PREFIX = `${TEAM_ROUTES.root}/`;

/** The landlord path's team-portal twin, or null when there isn't one. */
export function teamEquivalent(route) {
  if (typeof route !== "string" || !route.startsWith(LANDLORD_PREFIX)) return null;
  const candidate = TEAM_PREFIX + route.slice(LANDLORD_PREFIX.length);
  return TEAM_PATHS.has(candidate) ? candidate : null;
}

/**
 * Rewrite a tutorial for a portal.
 *
 * @param tutorial  one entry from the TUTORIALS registry
 * @param portal    "landlord" (unchanged) or "team"
 * @returns the tutorial, possibly with fewer steps, or null if unusable there
 */
export function portaliseTutorial(tutorial, portal) {
  if (!tutorial) return null;
  if (portal !== "team") return tutorial;

  const steps = [];
  for (const step of tutorial.steps || []) {
    // A step with no route is narration — it plays wherever the reader is.
    if (!step.route) {
      steps.push(step);
      continue;
    }
    const route = teamEquivalent(step.route);
    if (route) steps.push({ ...step, route });
    // else: this step drives a landlord-only screen. Drop it.
  }

  if (!steps.length) return null;
  return { ...tutorial, steps };
}

/**
 * The tutorials this viewer should be offered, already rewritten for their
 * portal.
 *
 * @param tutorials  the full registry
 * @param portal     "landlord" | "team"
 * @param can        usePermissions().can — always true for a landlord
 */
export function visibleTutorials(tutorials, portal, can) {
  return tutorials
    .filter((tutorial) => {
      // `module: null` means the tutorial explains the product rather than a
      // permissioned area (the welcome overview), so everyone sees it.
      if (!tutorial.module) return true;
      return can(tutorial.module, "view");
    })
    .map((tutorial) => portaliseTutorial(tutorial, portal))
    .filter(Boolean);
}
