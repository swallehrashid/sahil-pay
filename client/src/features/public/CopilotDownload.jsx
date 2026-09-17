import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import {
  Download, CheckCircle2, Smartphone, ShieldCheck, RefreshCw, FolderOpen, ToggleRight, KeyRound,
  AlertTriangle, MessageSquareText,
} from "lucide-react";
import { SahilPayMark } from "@/components/branding/SahilPayLogo";
import { useSeo } from "./useSeo";

// The one link sent to clients for the Co-pilot Android app: sahilpay.co.ke/copilot
//
// The APK ships WITH the website build (public/downloads/), so this link cannot
// break because an upload failed — the reason for this page. The download runs
// in the page so people SEE it happen: a progress ring around the Sahil Pay
// mark, megabytes and percent, then a clear "Downloaded" and what to do next.
// If the in-page download is not possible (old browser, blocked), a plain link
// does the same job.

const FALLBACK = {
  name: "Sahil Pay Co-pilot", version: "1.0.0", file: "/downloads/sahil-pay-copilot.apk",
  size_bytes: 19715074, sha256: "", min_android: "7.0",
};

const mb = (bytes) => `${(bytes / 1024 / 1024).toFixed(1)} MB`;

function ProgressRing({ progress, state }) {
  const radius = 70;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - Math.min(1, progress));
  return (
    <div className="relative mx-auto h-44 w-44" aria-hidden="true">
      <svg viewBox="0 0 160 160" className="h-full w-full -rotate-90">
        <circle cx="80" cy="80" r={radius} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="8" />
        <circle
          cx="80" cy="80" r={radius} fill="none"
          stroke={state === "done" ? "#34d399" : "#b95f7b"} strokeWidth="8" strokeLinecap="round"
          strokeDasharray={circumference} strokeDashoffset={state === "idle" ? circumference : offset}
          className="transition-[stroke-dashoffset] duration-300 ease-out"
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className={clsx("flex h-24 w-24 items-center justify-center rounded-full transition-all duration-500",
          state === "done" ? "bg-emerald-500/20 scale-110" : "bg-white/10",
          state === "downloading" && "animate-pulse")}>
          {state === "done"
            ? <CheckCircle2 className="h-12 w-12 animate-scale-in text-emerald-300" />
            : <SahilPayMark className="h-12 w-12 text-white" />}
        </span>
      </div>
    </div>
  );
}

export default function CopilotDownload() {
  useSeo({ title: "Download Sahil Pay Co-pilot", description: "Install the Sahil Pay Co-pilot Android app that records M-Pesa rent payments automatically.", path: "/copilot" });
  const [manifest, setManifest] = useState(FALLBACK);
  const [state, setState] = useState("idle"); // idle | downloading | done | error
  const [received, setReceived] = useState(0);
  const [total, setTotal] = useState(FALLBACK.size_bytes);
  const abortRef = useRef(null);
  const isIOS = typeof navigator !== "undefined" && /iPhone|iPad|iPod/i.test(navigator.userAgent);

  useEffect(() => {
    fetch("/downloads/copilot.json", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((m) => { if (m) { setManifest(m); setTotal(m.size_bytes); } })
      .catch(() => {});
    return () => abortRef.current?.abort();
  }, []);

  const fileUrl = `${manifest.file}${manifest.sha256 ? `?v=${manifest.sha256.slice(0, 12)}` : ""}`;
  const fileName = `sahil-pay-copilot-${manifest.version}.apk`;

  const start = async () => {
    setState("downloading");
    setReceived(0);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const res = await fetch(fileUrl, { signal: controller.signal });
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
      const length = Number(res.headers.get("Content-Length")) || manifest.size_bytes;
      setTotal(length);
      const reader = res.body.getReader();
      const chunks = [];
      let got = 0;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        got += value.length;
        setReceived(got);
      }
      const blob = new Blob(chunks, { type: "application/vnd.android.package-archive" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = fileName;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      setState("done");
    } catch (err) {
      if (err?.name === "AbortError") return;
      setState("error");
    }
  };

  const progress = total ? received / total : 0;
  const steps = [
    { icon: FolderOpen, title: "Open the file", text: `Tap “${fileName}” in your notifications or Downloads.` },
    { icon: ToggleRight, title: "Allow the install", text: "If Android asks, allow installs from this browser (Settings → Install unknown apps), then go back and tap Install." },
    { icon: KeyRound, title: "Connect your account", text: "Open Co-pilot and enter your agent code — find it in Sahil Pay under Settings → Co-pilot (SMS forwarding)." },
    { icon: MessageSquareText, title: "Allow SMS access", text: "Co-pilot reads only M-Pesa payment messages from the senders you choose, and forwards them securely." },
  ];

  return (
    <div className="app-bg min-h-screen px-4 py-8 sm:py-14">
      <main className="mx-auto w-full max-w-5xl">
        <header className="mb-8 flex items-center justify-center gap-2 text-white sm:mb-12">
          <SahilPayMark className="h-8 w-8" />
          <span className="font-serif text-xl tracking-[0.18em]">SAHIL PAY</span>
        </header>

        <div className="grid items-start gap-6 lg:grid-cols-[1.1fr_1fr]">
          <section className="glass p-6 text-center sm:p-10" aria-live="polite">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-secondary-200">Android app</p>
            <h1 className="mt-2 text-3xl font-light text-white sm:text-4xl">{manifest.name}</h1>
            <p className="mx-auto mt-3 max-w-md text-sm text-white/60 sm:text-base">
              Forwards your M-Pesa payment messages to Sahil Pay, so every rent payment records itself — no typing.
            </p>

            <div className="my-8"><ProgressRing progress={progress} state={state} /></div>

            {state === "idle" && (
              <>
                <button
                  onClick={start}
                  disabled={isIOS}
                  data-testid="copilot-download"
                  className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-secondary px-6 py-4 text-base font-semibold text-white shadow-xl shadow-secondary/30 transition hover:-translate-y-0.5 disabled:opacity-50 sm:w-auto"
                >
                  <Download className="h-5 w-5" /> Download Co-pilot
                </button>
                {isIOS && <p className="mt-3 text-sm text-amber-200">Co-pilot runs on Android phones. Open this link on the Android phone that receives your M-Pesa messages.</p>}
              </>
            )}

            {state === "downloading" && (
              <div className="space-y-3" data-testid="copilot-progress">
                <p className="text-2xl font-light text-white">{Math.round(progress * 100)}%</p>
                <p className="text-sm text-white/55">Downloading… {mb(received)} of {mb(total)}</p>
                <div className="mx-auto h-2 w-full max-w-sm overflow-hidden rounded-full bg-white/10"
                     role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)}>
                  <div className="h-full rounded-full bg-gradient-to-r from-secondary to-third transition-all duration-300" style={{ width: `${progress * 100}%` }} />
                </div>
                <p className="text-xs text-white/40">Keep this page open until it finishes.</p>
              </div>
            )}

            {state === "done" && (
              <div className="space-y-3" data-testid="copilot-done">
                <p className="text-2xl font-light text-white">Downloaded!</p>
                <p className="text-sm text-white/60">Now install it — follow the steps below.</p>
                <button onClick={() => setState("idle")} className="inline-flex items-center gap-1.5 text-sm text-white/50 hover:text-white">
                  <RefreshCw className="h-4 w-4" /> Download again
                </button>
              </div>
            )}

            {state === "error" && (
              <div className="space-y-3">
                <p className="flex items-center justify-center gap-2 text-white"><AlertTriangle className="h-5 w-5 text-amber-300" /> The download was interrupted.</p>
                <button onClick={start} className="rounded-xl bg-secondary px-5 py-3 font-medium text-white">Try again</button>
              </div>
            )}

            <dl className="mt-8 grid grid-cols-3 gap-2 text-xs sm:text-sm">
              <div className="rounded-xl bg-white/5 p-3"><dt className="text-white/45">Version</dt><dd className="mt-0.5 text-white">{manifest.version}</dd></div>
              <div className="rounded-xl bg-white/5 p-3"><dt className="text-white/45">Size</dt><dd className="mt-0.5 text-white">{mb(manifest.size_bytes)}</dd></div>
              <div className="rounded-xl bg-white/5 p-3"><dt className="text-white/45">Needs</dt><dd className="mt-0.5 text-white">Android {manifest.min_android}+</dd></div>
            </dl>
            <p className="mt-4 text-xs text-white/40">
              Download not starting? <a href={fileUrl} download={fileName} className="text-secondary-200 underline">Use the direct link</a>.
            </p>
          </section>

          <section className="space-y-4">
            <div className="glass p-6 sm:p-8">
              <h2 className="flex items-center gap-2 text-lg font-medium text-white"><Smartphone className="h-5 w-5 text-secondary-200" /> Install in four steps</h2>
              <ol className="mt-5 space-y-4">
                {steps.map((s, i) => (
                  <li key={s.title} className={clsx("flex gap-4 rounded-2xl p-3 transition-colors", state === "done" && i === 0 && "bg-secondary/15")}>
                    <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-secondary text-sm font-semibold text-white">{i + 1}</span>
                    <div>
                      <p className="flex items-center gap-2 font-medium text-white"><s.icon className="h-4 w-4 text-white/50" /> {s.title}</p>
                      <p className="mt-0.5 text-sm text-white/60">{s.text}</p>
                    </div>
                  </li>
                ))}
              </ol>
            </div>
            <div className="glass flex items-start gap-3 p-5">
              <ShieldCheck className="mt-0.5 h-5 w-5 flex-shrink-0 text-emerald-300" />
              <div className="text-sm text-white/60">
                <p className="text-white">Safe to install</p>
                <p className="mt-1">Published by Sahil Pay. Android warns about every app installed outside the Play Store — that is expected.</p>
                {manifest.sha256 && <p className="mt-2 break-all font-mono text-[11px] text-white/35">SHA-256 {manifest.sha256}</p>}
                <p className="mt-2">Need help? Call <a href="tel:0114129809" className="text-secondary-200">0114 129 809</a>.</p>
              </div>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}
