import { createContext, useEffect, useMemo } from "react";
import { useDispatch, useSelector } from "react-redux";
import { useGetMeQuery } from "@/features/auth/authApiSlice";
import { setCredentials, clearCredentials, selectAuth } from "@/features/auth/authSlice";
import { getAccessToken, setTokens, clearTokens } from "@/utils/tokenStorage";

// eslint-disable-next-line react-refresh/only-export-components -- intentional: context + provider share one file by design
export const AuthContext = createContext(null);

// Holds current user, role, permission matrix and impersonation flag. Hydrates from
// /api/auth/me on load whenever a token is present, and is the single source every
// <ProtectedRoutes> guard and portal sidebar reads from.
export function AuthProvider({ children }) {
  const dispatch = useDispatch();
  const { user, role, permissions, propertyAccess, impersonating } = useSelector(selectAuth);
  const hasToken = Boolean(getAccessToken());

  const { data, isLoading, isError } = useGetMeQuery(undefined, { skip: !hasToken });

  useEffect(() => {
    if (data) {
      // GET /api/auth/me returns the user record FLAT (id, email, role, …, profile),
      // not wrapped in a { user } envelope — so the payload itself IS the user.
      // permissions / property_access / impersonating are nested under it for the
      // roles that have them (team members; admins while impersonating).
      dispatch(
        setCredentials({
          user: data,
          role: data.role,
          permissions: data.permissions ?? null,
          propertyAccess: data.property_access ?? null,
          impersonating: data.impersonating ?? null,
        })
      );
    }
  }, [data, dispatch]);

  useEffect(() => {
    if (hasToken && isError) {
      clearTokens();
      dispatch(clearCredentials());
    }
  }, [hasToken, isError, dispatch]);

  const login = ({ accessToken, refreshToken, user: loggedInUser, role: loggedInRole, permissions: perms }) => {
    setTokens({ accessToken, refreshToken });
    dispatch(setCredentials({ user: loggedInUser, role: loggedInRole, permissions: perms ?? null }));
  };

  const logout = () => {
    dispatch(clearCredentials());
  };

  const isHydrating = hasToken && isLoading && !user;

  const value = useMemo(
    () => ({
      user,
      role,
      permissions,
      propertyAccess,
      impersonating,
      isAuthenticated: Boolean(user),
      isHydrating,
      login,
      logout,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [user, role, permissions, propertyAccess, impersonating, isHydrating]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export default AuthContext;
