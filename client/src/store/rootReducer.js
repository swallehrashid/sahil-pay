import authReducer from "@/features/auth/authSlice";

// Combines every non-RTK-Query slice reducer. Add new local slices here as the app grows —
// RTK Query state lives entirely under apiSlice.reducerPath instead.
export const rootReducers = {
  auth: authReducer,
};

export default rootReducers;
