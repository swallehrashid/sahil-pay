import { Link } from "react-router-dom";
import { ShieldCheck, Smartphone, BarChart3, Users, Banknote, FileText, ArrowRight } from "lucide-react";
import Button from "@/components/ui/Button";
import { AUTH_ROUTES, PUBLIC_ROUTES } from "@/config/routePaths";

const FEATURES = [
  { icon: Banknote, title: "M-Pesa native", text: "Paybill & till matching, STK push and bank-statement reconciliation out of the box." },
  { icon: FileText, title: "Invoicing that just works", text: "Rent, utilities, penalties and recurring bills — generated and sent automatically." },
  { icon: Users, title: "Built for teams", text: "Caretakers and property managers get a scoped, permissioned view of your portfolio." },
  { icon: BarChart3, title: "Insights, not spreadsheets", text: "Arrears, occupancy, and month-on-month performance at a glance." },
  { icon: Smartphone, title: "A portal tenants use", text: "Passwordless OTP login, balance breakdowns, and instant receipts." },
  { icon: ShieldCheck, title: "Audited, always", text: "Every action — yours, your team's, our support's — is logged and reversible." },
];

export default function Home() {
  return (
    <div>
      <section className="relative overflow-hidden px-6 pb-32 pt-24 text-center">
        <div className="absolute -left-32 top-0 h-96 w-96 animate-float-blob rounded-full bg-third/30 blur-3xl" />
        <div className="absolute -right-32 top-40 h-96 w-96 animate-float-blob rounded-full bg-secondary/20 blur-3xl" />

        <div className="relative z-10 mx-auto max-w-3xl animate-fade-in-up">
          <span className="glass inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-xs font-medium text-white/70">
            Property management, reimagined for Kenya
          </span>
          <h1 className="mt-6 text-4xl font-light tracking-wide text-white sm:text-6xl">
            Rent collection that feels <span className="text-secondary">effortless</span>.
          </h1>
          <p className="mx-auto mt-6 max-w-xl text-base text-white/60">
            SahilPay brings landlords, property managers, caretakers and tenants onto one
            platform — invoicing, M-Pesa reconciliation, maintenance, and reporting, all in one
            place.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
            <Link to={AUTH_ROUTES.register}>
              <Button size="lg" rightIcon={<ArrowRight className="h-4 w-4" />}>
                Start free trial
              </Button>
            </Link>
            <Link to={PUBLIC_ROUTES.features}>
              <Button variant="ghost" size="lg">
                Explore features
              </Button>
            </Link>
          </div>
        </div>
      </section>

      <section className="px-6 py-20">
        <div className="mx-auto max-w-6xl">
          <h2 className="text-center text-2xl font-light text-white">Everything a portfolio needs</h2>
          <div className="mt-12 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((feature, index) => (
              <div
                key={feature.title}
                className="glass card-hover animate-fade-in-up p-6"
                style={{ animationDelay: `${index * 80}ms` }}
              >
                <span className="inline-flex rounded-xl bg-secondary/15 p-3 text-secondary-200">
                  <feature.icon className="h-5 w-5" />
                </span>
                <h3 className="mt-4 text-base font-medium text-white">{feature.title}</h3>
                <p className="mt-2 text-sm text-white/50">{feature.text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="px-6 py-20">
        <div className="glass mx-auto max-w-4xl animate-fade-in-up p-10 text-center">
          <h2 className="text-2xl font-light text-white">Ready to see it in action?</h2>
          <p className="mt-3 text-sm text-white/60">
            Set up your account in minutes — no card required during your trial.
          </p>
          <Link to={AUTH_ROUTES.register} className="mt-6 inline-block">
            <Button size="lg">Get started for free</Button>
          </Link>
        </div>
      </section>
    </div>
  );
}
