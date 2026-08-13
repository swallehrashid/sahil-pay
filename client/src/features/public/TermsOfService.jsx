import { useSeo } from "./useSeo";

export default function TermsOfService() {
  useSeo({
    title: "Terms of Service — Sahil Pay",
    description:
      "The terms governing use of the Sahil Pay rental and property management platform.",
    path: "/terms",
  });

  return (
    <section className="mx-auto max-w-3xl px-6 py-24">
      <h1 className="animate-fade-in-up text-3xl font-light text-white">Terms of Service</h1>
      <p className="mt-2 text-sm text-white/40">Last updated: June 2026</p>
      <div className="mt-8 space-y-6 text-sm leading-relaxed text-white/60">
        <div>
          <h2 className="mb-2 text-base font-medium text-white">1. Using Sahil Pay</h2>
          <p>
            You agree to use the platform only for lawful property-management purposes and to
            keep your account credentials confidential.
          </p>
        </div>
        <div>
          <h2 className="mb-2 text-base font-medium text-white">2. Billing</h2>
          <p>
            Subscriptions are billed per the plan and billing cycle you select. Trials convert
            to a paid plan unless cancelled before the trial ends.
          </p>
        </div>
        <div>
          <h2 className="mb-2 text-base font-medium text-white">3. Data accuracy</h2>
          <p>
            You are responsible for the accuracy of tenant, property and financial data you
            enter. Sahil Pay is a record-keeping and automation tool, not a substitute for legal
            or accounting advice.
          </p>
        </div>
        <div>
          <h2 className="mb-2 text-base font-medium text-white">4. Termination</h2>
          <p>
            Either party may terminate the subscription at any time; your data remains
            available for export for a reasonable period afterward.
          </p>
        </div>
      </div>
    </section>
  );
}
