import authReducer from "@/features/auth/authSlice";
import tourReducer from "@/features/landlord/tutorials/tourSlice";

// Combines every non-RTK-Query slice reducer. Add new local slices here as the app grows —
// RTK Query state lives entirely under apiSlice.reducerPath instead.
export const rootReducers = {
  auth: authReducer,
  tour: tourReducer,
};

export default rootReducers;
