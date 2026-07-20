import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { useDispatch, useSelector } from "react-redux";
import { useAuth } from "@/hooks/useAuth";
import { useOnboardingState } from "./useOnboardingState";
import { getTutorial, ONBOARDING_SEQUENCE } from "./content";
import {
  selectTour,
  tourStarted,
  stepChanged,
  phaseAdvanced,
  tourExited,
  interstitialShown,
  interstitialDismissed,
  prerequisiteDialogShown,
  prerequisiteDialogDismissed,
} from "./tourSlice";
import TourOverlay from "./TourOverlay";
import ExplainerModal from "./ExplainerModal";
import WelcomeModal from "./WelcomeModal";
import SequenceInterstitial from "./SequenceInterstitial";
import PrerequisiteDialog from "./PrerequisiteDialog";

const TourContext = createContext(null);

// eslint-disable-next-line react-refresh/only-export-components -- intentional: context + provider + hook share one file by design (mirrors AuthContext.jsx)
export function useTour() {
  const ctx = useContext(TourContext);
  if (!ctx) throw new Error("useTour must be used within a <TourProvider>");
  return ctx;
}

// Mounted once inside the landlord layout (AppRoutes.jsx) so it survives route changes
// (ONBOARDING_TUTORIALS_SPEC.md §5.2). Owns the welcome modal, the active tour/explainer
// overlay, sequence interstitials and prerequisite gating — every other component talks to
// this only through useTour().startTutorial(id).
export default function TourProvider({ children }) {
  const dispatch = useDispatch();
  const tour = useSelector(selectTour);
  const { impersonating } = useAuth();
  const onboarding = useOnboardingState();
  const [welcomeDismissedThisSession, setWelcomeDismissedThisSession] = useState(false);

  const startTutorial = useCallback(
    (id, opts = {}) => {
      if (!onboarding.isEligible) return;
      const tutorial = getTutorial(id);
      if (!tutorial) return;

      if (!opts.skipPrerequisiteCheck && tutorial.prerequisite && !tutorial.prerequisite.soft) {
        const have = onboarding.counts[tutorial.prerequisite.count] ?? 0;
        if (have === 0) {
          dispatch(prerequisiteDialogShown({ tutorialId: id, prerequisiteTutorialId: tutorial.prerequisite.tutorialId }));
          return;
        }
      }

      const initialMode = tutorial.mode === "tour" ? "tour" : "explainer";
      dispatch(
        tourStarted({
          tutorialId: id,
          mode: initialMode,
          origin: opts.origin ?? "standalone",
          sequenceIds: opts.sequenceIds ?? null,
          sequencePos: opts.sequencePos ?? null,
        })
      );
    },
    [dispatch, onboarding]
  );

  const startSequence = useCallback(() => {
    const idx = ONBOARDING_SEQUENCE.findIndex((id) => onboarding.tutorialStatus(id) !== "completed");
    if (idx === -1) return;
    startTutorial(ONBOARDING_SEQUENCE[idx], {
      origin: "onboarding-sequence",
      sequenceIds: ONBOARDING_SEQUENCE,
      sequencePos: idx,
      skipPrerequisiteCheck: true,
    });
  }, [onboarding, startTutorial]);

  const finishCurrentTutorial = useCallback(
    (status) => {
      const id = tour.activeTutorialId;
      if (status && id) onboarding.markTutorial(id, status);
      if (status === "completed" && tour.origin === "onboarding-sequence" && tour.sequenceIds) {
        const nextPos = (tour.sequencePos ?? 0) + 1;
        const nextId = tour.sequenceIds[nextPos];
        if (nextId) {
          dispatch(interstitialShown({ finishedId: id, nextId }));
          return;
        }
      }
      dispatch(tourExited());
    },
    [dispatch, onboarding, tour.activeTutorialId, tour.origin, tour.sequenceIds, tour.sequencePos]
  );

  const activeTutorial = tour.activeTutorialId ? getTutorial(tour.activeTutorialId) : null;

  // ---- Tour-mode (spotlight) handlers ----
  const handleTourNext = useCallback(() => {
    if (!activeTutorial) return;
    if (tour.stepIndex < activeTutorial.steps.length - 1) {
      dispatch(stepChanged(tour.stepIndex + 1));
    } else {
      finishCurrentTutorial("completed");
    }
  }, [activeTutorial, dispatch, finishCurrentTutorial, tour.stepIndex]);

  const handleTourBack = useCallback(() => {
    if (tour.stepIndex > 0) dispatch(stepChanged(tour.stepIndex - 1));
  }, [dispatch, tour.stepIndex]);

  const handleTourExit = useCallback(() => {
    finishCurrentTutorial(tour.stepIndex === 0 ? null : "skipped");
  }, [finishCurrentTutorial, tour.stepIndex]);

  // ---- Explainer-mode (slide carousel) handlers ----
  const handleExplainerNext = useCallback(() => {
    if (!activeTutorial) return;
    if (tour.stepIndex < activeTutorial.slides.length - 1) dispatch(stepChanged(tour.stepIndex + 1));
  }, [activeTutorial, dispatch, tour.stepIndex]);

  const handleExplainerBack = useCallback(() => {
    if (tour.stepIndex > 0) dispatch(stepChanged(tour.stepIndex - 1));
  }, [dispatch, tour.stepIndex]);

  const handleExplainerDone = useCallback(() => {
    if (activeTutorial?.mode === "mixed") {
      dispatch(phaseAdvanced("tour"));
    } else {
      finishCurrentTutorial("completed");
    }
  }, [activeTutorial, dispatch, finishCurrentTutorial]);

  const handleExplainerSkip = useCallback(() => {
    finishCurrentTutorial("skipped");
  }, [finishCurrentTutorial]);

  // ---- Sequence interstitial ----
  const handleInterstitialContinue = useCallback(() => {
    if (!tour.interstitial) return;
    const nextPos = tour.sequenceIds?.indexOf(tour.interstitial.nextId) ?? -1;
    startTutorial(tour.interstitial.nextId, {
      origin: "onboarding-sequence",
      sequenceIds: tour.sequenceIds,
      sequencePos: nextPos,
      skipPrerequisiteCheck: true,
    });
  }, [startTutorial, tour.interstitial, tour.sequenceIds]);

  const handleInterstitialFinishLater = useCallback(() => {
    dispatch(interstitialDismissed());
  }, [dispatch]);

  // ---- Prerequisite dialog ----
  const handlePrerequisiteStart = useCallback(() => {
    const prereqId = tour.prerequisiteDialog?.prerequisiteTutorialId;
    dispatch(prerequisiteDialogDismissed());
    if (prereqId) startTutorial(prereqId, { origin: "standalone" });
  }, [dispatch, startTutorial, tour.prerequisiteDialog]);

  const handlePrerequisiteCancel = useCallback(() => {
    dispatch(prerequisiteDialogDismissed());
  }, [dispatch]);

  // ---- Welcome modal ----
  const isReturning = useMemo(
    () => Object.values(onboarding.counts).some((c) => c > 0),
    [onboarding.counts]
  );
  const shouldShowWelcome =
    onboarding.isEligible &&
    onboarding.isHydrated &&
    !impersonating &&
    !onboarding.state?.welcome_seen_at &&
    !tour.activeTutorialId &&
    !tour.interstitial &&
    !welcomeDismissedThisSession;

  const handleWelcomeStart = useCallback(() => {
    onboarding.markWelcomeSeen();
    setWelcomeDismissedThisSession(true);
    startSequence();
  }, [onboarding, startSequence]);

  const handleWelcomeSkip = useCallback(() => {
    onboarding.markWelcomeSeen();
    setWelcomeDismissedThisSession(true);
  }, [onboarding]);

  const contextValue = useMemo(
    () => ({
      startTutorial,
      startSequence,
      tutorialStatus: onboarding.tutorialStatus,
      counts: onboarding.counts,
      isEligible: onboarding.isEligible,
    }),
    [startTutorial, startSequence, onboarding.tutorialStatus, onboarding.counts, onboarding.isEligible]
  );

  const sequenceMeta =
    tour.origin === "onboarding-sequence" && tour.sequenceIds
      ? { sequencePos: tour.sequencePos ?? 0, sequenceLen: tour.sequenceIds.length }
      : null;

  return (
    <TourContext.Provider value={contextValue}>
      {children}

      {shouldShowWelcome && (
        <WelcomeModal isOpen isReturning={isReturning} onStart={handleWelcomeStart} onSkip={handleWelcomeSkip} />
      )}

      {activeTutorial && tour.mode === "tour" && (
        <TourOverlay
          tutorial={activeTutorial}
          stepIndex={tour.stepIndex}
          sequenceMeta={sequenceMeta}
          onNext={handleTourNext}
          onBack={handleTourBack}
          onExit={handleTourExit}
        />
      )}

      {activeTutorial && tour.mode === "explainer" && (
        <ExplainerModal
          tutorial={activeTutorial}
          slideIndex={tour.stepIndex}
          onNext={handleExplainerNext}
          onBack={handleExplainerBack}
          onDone={handleExplainerDone}
          onSkip={handleExplainerSkip}
          doneLabel={activeTutorial.mode === "mixed" ? "Continue" : "Done"}
        />
      )}

      {tour.interstitial && (
        <SequenceInterstitial
          finishedTitle={getTutorial(tour.interstitial.finishedId)?.title ?? ""}
          nextTitle={getTutorial(tour.interstitial.nextId)?.title ?? ""}
          nextDuration={getTutorial(tour.interstitial.nextId)?.duration ?? ""}
          onContinue={handleInterstitialContinue}
          onFinishLater={handleInterstitialFinishLater}
        />
      )}

      {tour.prerequisiteDialog && (
        <PrerequisiteDialog
          prerequisiteTitle={getTutorial(tour.prerequisiteDialog.prerequisiteTutorialId)?.title ?? ""}
          onStart={handlePrerequisiteStart}
          onCancel={handlePrerequisiteCancel}
        />
      )}
    </TourContext.Provider>
  );
}
