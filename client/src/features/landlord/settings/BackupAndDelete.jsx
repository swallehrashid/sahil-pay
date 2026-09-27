import { useState } from "react";
import { useDispatch } from "react-redux";
import { AlertTriangle, Download, Trash2 } from "lucide-react";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import Modal from "@/components/ui/Modal";
import { toast } from "@/components/ui/Toast";
import { apiSlice } from "@/store/apiSlice";
import { downloadFile } from "@/utils/downloadFile";
import { LANDLORD_ROUTES } from "@/config/routePaths";
import { useGetWipeInfoQuery, useVerifyWipePasswordMutation, useWipeAccountMutation } from "./settingsApiSlice";

const LABELS = {
  properties: "properties", units: "units", tenants: "tenants", invoices: "invoices",
  payments: "payments", utility_readings: "utility readings", expenses: "expenses",
  leases: "leases", owners: "owners / landlords",
};

/**
 * Backup & Delete — for accounts that were loaded with test data and want a
 * clean start. Four deliberate steps: are you sure → your password → type the
 * phrase exactly → final "this is permanent". The server backs everything up
 * to an Excel workbook first and only deletes once that file exists.
 */
export default function BackupAndDelete() {
  const [isOpen, setIsOpen] = useState(false);
  return (
    <div className="glass space-y-3 border border-secondary/40 p-6" data-testid="backup-and-delete">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-5 w-5 flex-shrink-0 text-secondary" />
        <div>
          <h3 className="text-base font-medium text-white">Back up and delete everything</h3>
          <p className="mt-1 text-sm text-white/60">
            Downloads a full backup of every property, unit, tenant, invoice and payment, then deletes all of
            them so you can start over with a clean account. Your login, settings, SMS balance, subscription,
            connections and team members stay. <strong className="text-white/80">This cannot be undone</strong> —
            the only way back is to bulk upload your data again.
          </p>
          <p className="mt-1 text-xs text-white/40">Only the account owner can do this.</p>
        </div>
      </div>
      <div className="flex justify-end">
        <Button variant="danger" leftIcon={<Trash2 className="h-4 w-4" />} onClick={() => setIsOpen(true)}
                data-testid="wipe-open">
          Back up and delete everything
        </Button>
      </div>
      {isOpen && <WipeFlow onClose={() => setIsOpen(false)} />}
    </div>
  );
}

function WipeFlow({ onClose }) {
  const dispatch = useDispatch();
  const { data: info, isLoading } = useGetWipeInfoQuery();
  const [verify, { isLoading: verifying }] = useVerifyWipePasswordMutation();
  const [wipe, { isLoading: wiping }] = useWipeAccountMutation();

  const [step, setStep] = useState(1);
  const [password, setPassword] = useState("");
  const [passwordError, setPasswordError] = useState("");
  const [token, setToken] = useState(null);
  const [phrase, setPhrase] = useState("");
  const [result, setResult] = useState(null);

  const expected = info?.phrase ?? "";
  const counts = info?.counts ?? {};
  const total = Object.values(counts).reduce((a, b) => a + (b || 0), 0);

  const checkPassword = async (e) => {
    e.preventDefault();
    setPasswordError("");
    try {
      const res = await verify({ password }).unwrap();
      setToken(res.wipe_token);
      setPassword("");
      setStep(3);
    } catch (err) {
      setPasswordError(err?.data?.error || "That password is not correct.");
    }
  };

  const fetchBackup = (res) =>
    downloadFile(`/settings/backup/${res.backup_id}/download`, {
      filename: `sahilpay-backup-${info?.account_number || "account"}.xlsx`, format: "xlsx",
    });

  const runWipe = async () => {
    try {
      const res = await wipe({ wipe_token: token, phrase, confirm: true }).unwrap();
      setResult(res);
      setStep(5);
      // Every cached list now describes records that no longer exist.
      dispatch(apiSlice.util.resetApiState());
      try {
        await fetchBackup(res);
      } catch {
        toast("Your data was deleted, but the backup did not download. Use the button to download it.", { type: "error", duration: 10000 });
      }
    } catch (err) {
      toast(err?.data?.error || "Nothing was deleted — the backup and delete did not run.", { type: "error", duration: 9000 });
      if (err?.status === 403) setStep(2);
    }
  };

  return (
    <Modal isOpen onClose={wiping ? () => {} : onClose} title={step === 5 ? "Done" : `Back up and delete everything · step ${step} of 4`}>
      {isLoading && <p className="text-sm text-white/50">Checking your account…</p>}

      {!isLoading && step === 1 && (
        <div className="space-y-4" data-testid="wipe-step-1">
          <p className="text-sm text-white/80">Are you sure you want to back up and delete everything?</p>
          <ul className="grid grid-cols-2 gap-1 rounded-xl bg-white/5 p-3 text-sm text-white/70">
            {Object.entries(counts).map(([k, v]) => (
              <li key={k}><strong className="text-white">{Number(v).toLocaleString()}</strong> {LABELS[k] ?? k}</li>
            ))}
          </ul>
          <p className="text-xs text-white/50">
            All of the above will be backed up to a file you download, and then permanently deleted from Sahil Pay.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button variant="danger" onClick={() => setStep(2)} data-testid="wipe-step-1-yes">
              Yes, continue
            </Button>
          </div>
        </div>
      )}

      {step === 2 && (
        <form className="space-y-4" onSubmit={checkPassword} data-testid="wipe-step-2">
          <p className="text-sm text-white/80">Enter your account password to continue.</p>
          <Input label="Password" type="password" autoComplete="current-password" value={password}
                 onChange={(e) => setPassword(e.target.value)} error={passwordError} required
                 data-testid="wipe-password" />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>Cancel</Button>
            <Button type="submit" variant="danger" isLoading={verifying} data-testid="wipe-password-submit">
              Confirm password
            </Button>
          </div>
        </form>
      )}

      {step === 3 && (
        <div className="space-y-4" data-testid="wipe-step-3">
          <p className="text-sm text-white/80">
            Type <code className="rounded bg-white/10 px-1.5 py-0.5 text-white" data-testid="wipe-phrase">{expected}</code> exactly as shown.
          </p>
          <Input label="Confirmation" value={phrase} onChange={(e) => setPhrase(e.target.value)}
                 autoComplete="off" data-testid="wipe-phrase-input"
                 error={phrase && phrase !== expected && !expected.startsWith(phrase) ? "That does not match." : undefined} />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>Cancel</Button>
            <Button variant="danger" disabled={phrase !== expected} onClick={() => setStep(4)} data-testid="wipe-phrase-ok">
              OK
            </Button>
          </div>
        </div>
      )}

      {step === 4 && (
        <div className="space-y-4" data-testid="wipe-step-4">
          <div className="rounded-xl border border-secondary/50 bg-secondary/10 p-4 text-sm text-white/85">
            <p className="font-medium">Last chance. This is permanent.</p>
            <p className="mt-1 text-white/70">
              {total.toLocaleString()} records will be backed up and then deleted. There is no undo — the only way
              to get them back is to bulk upload them again from the backup file.
            </p>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose} disabled={wiping}>Cancel</Button>
            <Button variant="danger" isLoading={wiping} onClick={runWipe} data-testid="wipe-final">
              Back up and delete everything
            </Button>
          </div>
          {wiping && <p className="text-xs text-white/50">Backing up… then deleting. Keep this window open.</p>}
        </div>
      )}

      {step === 5 && result && (
        <div className="space-y-4" data-testid="wipe-done">
          <p className="text-sm text-white/80">{result.message}</p>
          <ul className="grid grid-cols-2 gap-1 rounded-xl bg-white/5 p-3 text-sm text-white/70">
            {Object.entries(result.deleted).map(([k, v]) => (
              <li key={k}>{Number(v).toLocaleString()} {LABELS[k] ?? k} deleted</li>
            ))}
          </ul>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" leftIcon={<Download className="h-4 w-4" />} onClick={() => fetchBackup(result)}
                    data-testid="wipe-download">
              Download the backup again
            </Button>
            <Button onClick={() => window.location.assign(LANDLORD_ROUTES.dashboard)}>Go to dashboard</Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
