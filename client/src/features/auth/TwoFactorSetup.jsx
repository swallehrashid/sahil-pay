import { useEffect, useState } from "react";
import { ShieldCheck, Copy, Check, Download, AlertTriangle } from "lucide-react";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import { toast } from "@/components/ui/Toast";
import { env } from "@/config/env";
import { getAccessToken } from "@/utils/tokenStorage";

/**
 * Enrol in two-factor authentication.
 *
 * Mandatory for admins: an admin account reaches every landlord's money and
 * every tenant's phone number, so a password alone is not an acceptable guard.
 * Until this is done, the admin portal stays shut.
 *
 * The QR code is rendered from the otpauth:// URI locally rather than through
 * an image service — sending the provisioning URI (which contains the secret)
 * to a third party to be drawn would defeat the entire exercise.
 */

async function api(path, body) {
  const res = await fetch(`${env.apiBaseUrl}${path}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${getAccessToken()}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body ?? {}),
  });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(payload.error || "Something went wrong.");
  return payload;
}

/** Minimal QR renderer — no network, no third party sees the secret. */
function QrCode({ text, size = 190 }) {
  const [svg, setSvg] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // Loaded on demand so the whole app doesn't carry a QR library.
        const { default: QRCode } = await import("qrcode");
        const markup = await QRCode.toString(text, {
          type: "svg", margin: 1, width: size,
          color: { dark: "#0f0246", light: "#ffffff" },
        });
        if (!cancelled) setSvg(markup);
      } catch {
        if (!cancelled) setSvg(null);
      }
    })();
    return () => { cancelled = true; };
  }, [text, size]);

  if (!svg) {
    return (
      <div
        className="flex items-center justify-center rounded-xl bg-white/5 text-center text-xs text-white/40"
        style={{ width: size, height: size }}
      >
        Type the key in by hand instead
      </div>
    );
  }
  return (
    <div
      className="rounded-xl bg-white p-2"
      style={{ width: size + 16 }}
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}

export default function TwoFactorSetup({ onComplete, required = false }) {
  const [stage, setStage] = useState("start");   // start | scan | codes
  const [secret, setSecret] = useState(null);
  const [uri, setUri] = useState(null);
  const [code, setCode] = useState("");
  const [backupCodes, setBackupCodes] = useState([]);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  async function begin() {
    setBusy(true);
    try {
      const data = await api("/auth/2fa/setup");
      setSecret(data.secret);
      setUri(data.provisioning_uri);
      setStage("scan");
    } catch (err) {
      toast(err.message, { type: "error" });
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    setBusy(true);
    try {
      const data = await api("/auth/2fa/enable", { code });
      setBackupCodes(data.backup_codes || []);
      setStage("codes");
    } catch (err) {
      toast(err.message, { type: "error" });
    } finally {
      setBusy(false);
    }
  }

  function copySecret() {
    navigator.clipboard?.writeText(secret).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  function downloadCodes() {
    const body = [
      "Sahil Pay — two-factor backup codes",
      "",
      "Each code works ONCE. Keep them somewhere safe and offline.",
      "",
      ...backupCodes,
    ].join("\n");
    const url = URL.createObjectURL(new Blob([body], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "sahilpay-backup-codes.txt";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="glass mx-auto max-w-lg space-y-5 p-6">
      <div className="flex items-start gap-3">
        <ShieldCheck className="mt-0.5 h-6 w-6 flex-shrink-0 text-secondary" />
        <div>
          <h2 className="text-lg font-light tracking-wide text-white">
            Two-factor authentication
          </h2>
          <p className="mt-1 text-sm leading-relaxed text-white/55">
            {required
              ? "Admin accounts can reach every landlord's money and every tenant's details, so a password alone isn't enough. Set this up to continue."
              : "Add a second step to sign-in, so a stolen password on its own isn't enough to get in."}
          </p>
        </div>
      </div>

      {stage === "start" && (
        <>
          <ol className="space-y-2 text-sm text-white/60">
            <li>1. Install an authenticator app — Google Authenticator, Authy, or your password manager.</li>
            <li>2. Scan the code we show you.</li>
            <li>3. Type the 6-digit number back to confirm.</li>
          </ol>
          <Button onClick={begin} isLoading={busy}>Get started</Button>
        </>
      )}

      {stage === "scan" && (
        <>
          <div className="flex flex-col items-center gap-4">
            <QrCode text={uri} />
            <div className="w-full rounded-xl border border-white/10 bg-white/[0.03] p-3 text-center">
              <p className="text-xs text-white/45">Can't scan? Enter this key by hand:</p>
              <div className="mt-1.5 flex items-center justify-center gap-2">
                <code className="break-all font-mono text-sm text-white">{secret}</code>
                <button
                  type="button"
                  onClick={copySecret}
                  className="flex-shrink-0 text-white/40 transition-colors hover:text-white"
                  aria-label="Copy key"
                >
                  {copied ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
                </button>
              </div>
            </div>
          </div>

          <Input
            label="6-digit code from your app"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
            placeholder="123456"
            inputMode="numeric"
            autoComplete="one-time-code"
          />
          <Button onClick={confirm} isLoading={busy} disabled={code.length !== 6}>
            Turn on two-factor
          </Button>
        </>
      )}

      {stage === "codes" && (
        <>
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4">
            <p className="flex items-start gap-2 text-sm text-amber-100">
              <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
              <span>
                Save these backup codes now. Each works once, and we can't show
                them again — they're how you get in if you lose your phone.
              </span>
            </p>
          </div>

          <div className="grid grid-cols-2 gap-2 rounded-xl border border-white/10 bg-white/[0.03] p-4">
            {backupCodes.map((backupCode) => (
              <code key={backupCode} className="font-mono text-sm text-white">
                {backupCode}
              </code>
            ))}
          </div>

          <div className="flex flex-wrap gap-3">
            <Button variant="ghost" leftIcon={<Download className="h-4 w-4" />} onClick={downloadCodes}>
              Download codes
            </Button>
            <Button onClick={() => onComplete?.()}>I've saved them — continue</Button>
          </div>
        </>
      )}
    </div>
  );
}
