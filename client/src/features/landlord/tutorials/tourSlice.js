import { createSlice } from "@reduxjs/toolkit";

// Runtime state for the active tour/explainer (ONBOARDING_TUTORIALS_SPEC.md §5.2). Content
// (steps, copy, icons) is never stored here — only ids/indices — everything non-serializable
// (lucide icon components) is resolved from the content registry by the component layer.
const initialState = {
  activeTutorialId: null,
  stepIndex: 0,
  mode: null, // 'tour' | 'explainer' | null
  origin: null, // 'onboarding-sequence' | 'standalone' | null
  sequenceIds: null,
  sequencePos: null,
  // Centered interstitial shown between two tutorials in a sequence (§7.0).
  interstitial: null, // { finishedId, nextId } | null
  // Prerequisite-gap confirmation dialog (§10.3).
  prerequisiteDialog: null, // { tutorialId, prerequisiteTutorialId } | null
};

const tourSlice = createSlice({
  name: "tour",
  initialState,
  reducers: {
    tourStarted: (state, action) => {
      const { tutorialId, mode, origin = "standalone", sequenceIds = null, sequencePos = null } = action.payload;
      state.activeTutorialId = tutorialId;
      state.stepIndex = 0;
      state.mode = mode;
      state.origin = origin;
      state.sequenceIds = sequenceIds;
      state.sequencePos = sequencePos;
      state.interstitial = null;
      state.prerequisiteDialog = null;
    },
    stepChanged: (state, action) => {
      state.stepIndex = action.payload;
    },
    // Mixed tutorials (explainer slides, then a mini-tour) transition phase without
    // resetting origin/sequence position — only the tourSlice's own start/exit actions do that.
    phaseAdvanced: (state, action) => {
      state.mode = action.payload;
      state.stepIndex = 0;
    },
    tourExited: () => initialState,
    interstitialShown: (state, action) => {
      state.activeTutorialId = null;
      state.mode = null;
      state.interstitial = action.payload; // { finishedId, nextId }
    },
    interstitialDismissed: (state) => {
      state.interstitial = null;
      // Dismissing without "Continue" ends the sequence entirely.
      state.origin = null;
      state.sequenceIds = null;
      state.sequencePos = null;
    },
    prerequisiteDialogShown: (state, action) => {
      state.prerequisiteDialog = action.payload; // { tutorialId, prerequisiteTutorialId }
    },
    prerequisiteDialogDismissed: (state) => {
      state.prerequisiteDialog = null;
    },
  },
});

export const {
  tourStarted,
  stepChanged,
  phaseAdvanced,
  tourExited,
  interstitialShown,
  interstitialDismissed,
  prerequisiteDialogShown,
  prerequisiteDialogDismissed,
} = tourSlice.actions;

export const selectTour = (state) => state.tour;

export default tourSlice.reducer;
