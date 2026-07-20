import { createSlice } from "@reduxjs/toolkit";
import { clearTokens } from "@/utils/tokenStorage";

const initialState = {
  user: null,
  role: null,
  permissions: null, // { [module]: { can_view, can_edit } } — team members only, null = unrestricted
  propertyAccess: null, // { all: bool, propertyIds: [] } — team members only
  impersonating: null, // { landlordId, companyName } when an admin is impersonating this account
};

const authSlice = createSlice({
  name: "auth",
  initialState,
  reducers: {
    setCredentials: (state, action) => {
      const { user, role, permissions, propertyAccess, impersonating } = action.payload;
      if (user !== undefined) state.user = user;
      if (role !== undefined) state.role = role;
      if (permissions !== undefined) state.permissions = permissions;
      if (propertyAccess !== undefined) state.propertyAccess = propertyAccess;
      if (impersonating !== undefined) state.impersonating = impersonating;
    },
    clearCredentials: () => {
      clearTokens();
      return initialState;
    },
  },
});

export const { setCredentials, clearCredentials } = authSlice.actions;

export const selectAuth = (state) => state.auth;
export const selectCurrentUser = (state) => state.auth.user;
export const selectCurrentRole = (state) => state.auth.role;
export const selectIsImpersonating = (state) => Boolean(state.auth.impersonating);

export default authSlice.reducer;
