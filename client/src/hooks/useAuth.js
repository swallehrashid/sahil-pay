import { useContext } from "react";
import { AuthContext } from "@/context/AuthContext";

// Sugar over AuthContext: { user, role, permissions, propertyAccess, impersonating,
// isAuthenticated, isHydrating, login, logout }
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an <AuthProvider>");
  }
  return ctx;
}

export default useAuth;
