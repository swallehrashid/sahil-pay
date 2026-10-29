import { useEffect, useRef, useState } from "react";
import { toast } from "@/components/ui/Toast";
import { env } from "@/config/env";
import { useGoogleAuthMutation } from "../authApiSlice";

// Loads Google Identity Services once for the whole app.
let gsiPromise = null;
function loadGsi() {
  if (gsiPromise) return gsiPromise;
  gsiPromise = new Promise((resolve, reject) => {
    if (window.google?.accounts?.id) return resolve();
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true;
    s.defer = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("Could not load Google Sign-In."));
    document.head.appendChild(s);
  });
  return gsiPromise;
}

/**
 * "Continue with Google" for landlords and affiliates.
 *
 * Renders Google's official button, exchanges the returned ID token with our
 * backend (POST /auth/google), and hands the server's response to `onResult`
 * so the parent page decides where to go (login vs. just-created, 2FA, or the
 * "finish your details" step). Renders nothing when no client ID is configured,
 * so the app degrades cleanly to password-only.
 *
 * Props:
 *   intent      "landlord" | "affiliate" — role to create a NEW account as
 *   getExtra()  optional: returns extra fields to send (account_type, phone, …)
 *   onResult    (serverResponse) => void
 *   text        Google button text: "signin_with" | "signup_with" | "continue_with"
 *   dividerText optional label for the "— or —" divider shown above the button
 */
export default function GoogleSignInButton({
  intent = "landlord",
  getExtra,
  onResult,
  text = "continue_with",
  dividerText = "or",
}) {
  const clientId = env.googleClientId;
  const holderRef = useRef(null);
  const [ready, setReady] = useState(false);
  const [googleAuth, { isLoading }] = useGoogleAuthMutation();

  // Keep the latest props in refs so the one-time GIS callback never goes stale.
  const cbRef = useRef({ intent, getExtra, onResult, googleAuth });
  cbRef.current = { intent, getExtra, onResult, googleAuth };

  useEffect(() => {
    if (!clientId) return;
    let cancelled = false;

    const handleCredential = async ({ credential }) => {
      const { intent, getExtra, onResult, googleAuth } = cbRef.current;
      if (!credential) return;
      try {
        const extra = (getExtra && getExtra()) || {};
        const result = await googleAuth({ credential, intent, ...extra }).unwrap();
        onResult?.(result);
      } catch (err) {
        toast(err?.data?.error || "Google sign-in failed. Please try again.", { type: "error" });
      }
    };

    loadGsi()
      .then(() => {
        if (cancelled || !window.google?.accounts?.id) return;
        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: handleCredential,
        });
        if (holderRef.current) {
          holderRef.current.innerHTML = "";
          window.google.accounts.id.renderButton(holderRef.current, {
            type: "standard",
            theme: "outline",
            size: "large",
            text,
            shape: "pill",
            logo_alignment: "left",
            width: 320,
          });
        }
        setReady(true);
      })
      .catch(() => {
        toast("Could not load Google Sign-In. Check your connection.", { type: "error" });
      });

    return () => { cancelled = true; };
  }, [clientId, text]);

  if (!clientId) return null;

  return (
    <div className="mt-6">
      {dividerText && (
        <div className="relative mb-4 flex items-center" aria-hidden="true">
          <div className="flex-grow border-t border-white/10" />
          <span className="mx-3 text-xs uppercase tracking-wide text-white/40">{dividerText}</span>
          <div className="flex-grow border-t border-white/10" />
        </div>
      )}
      {/* Google renders its branded button here. The overlay keeps the button
          from being clicked while a verification request is already in flight. */}
      <div className="relative flex justify-center">
        <div ref={holderRef} />
        {(isLoading || !ready) && (
          <div
            className="absolute inset-0 cursor-wait"
            title={isLoading ? "Signing you in…" : "Loading Google…"}
          />
        )}
      </div>
    </div>
  );
}
