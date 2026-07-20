import { useState } from "react";
import { Link } from "react-router-dom";
import { Mail, Lock, User, Phone, TrendingUp, Users, Wallet, CheckCircle2 } from "lucide-react";
import Input from "@/components/ui/Input";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { isRequired, isValidEmail, isValidPhone } from "@/utils/validators";
import { AUTH_ROUTES } from "@/config/routePaths";
import Section from "./components/Section";
import Reveal from "./components/Reveal";
import { FeatureCard } from "./components/pieces";
import { useGetPublicAffiliateProgramQuery } from "./publicApiSlice";
import { useRegisterAffiliateMutation } from "@/features/affiliate/affiliateApiSlice";

export default function AffiliateSignup() {
  const { data: program, isLoading: isLoadingProgram } = useGetPublicAffiliateProgramQuery();
  const [registerAffiliate, { isLoading }] = useRegisterAffiliateMutation();
  const [form, setForm] = useState({ full_name: "", email: "", phone: "", password: "" });
  const [errors, setErrors] = useState({});
  const [submitted, setSubmitted] = useState(false);

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const rate = program?.default_commission_rate ? Math.round(Number(program.default_commission_rate)) : 40;
  const months = program?.default_commission_months ?? 4;
  const programActive = !isLoadingProgram && program?.is_active !== false;

  const handleSubmit = async (e) => {
    e.preventDefault();
    const nextErrors = {};
    if (!isRequired(form.full_name)) nextErrors.full_name = "Your name is required";
    if (!isRequired(form.email) || !isValidEmail(form.email)) nextErrors.email = "Enter a valid email";
    if (!isValidPhone(form.phone)) nextErrors.phone = "Enter a valid phone number";
    if (!form.password || form.password.length < 8) nextErrors.password = "Use at least 8 characters";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    try {
      await registerAffiliate(form).unwrap();
      setSubmitted(true);
    } catch (err) {
      toast(err?.data?.error || "Could not create your affiliate account.", { type: "error" });
    }
  };

  return (
    <div>
      {/* Hero */}
      <section className="relative overflow-hidden px-6 pb-8 pt-20 text-center sm:pt-24">
        <div className="absolute -left-32 top-0 h-96 w-96 animate-float-blob rounded-full bg-third/20 blur-3xl" />
        <div className="relative z-10 mx-auto max-w-3xl animate-fade-in-up">
          <span className="glass inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-xs font-medium text-white/70">
            Sahil Pay Affiliate Program
          </span>
          <h1 className="mt-6 text-4xl font-light tracking-wide text-white sm:text-5xl">
            Earn {rate}% for every landlord you refer
          </h1>
          <p className="mx-auto mt-5 max-w-xl text-base leading-relaxed text-white/60">
            Refer a landlord to Sahil Pay and earn {rate}% of their subscription for their first {months} paid
            months — automatically, transparently, and withdrawable straight to M-Pesa.
          </p>
        </div>
      </section>

      {!programActive && (
        <Section className="!pt-4">
          <div className="glass mx-auto max-w-2xl border border-amber-500/30 bg-amber-500/10 p-6 text-center text-sm text-amber-200">
            The affiliate program isn't currently accepting new signups. Check back soon.
          </div>
        </Section>
      )}

      {/* How it works */}
      <Section center eyebrow="How it works" title="Simple, transparent, automatic">
        <div className="mt-10 grid grid-cols-1 gap-6 md:grid-cols-3">
          <FeatureCard icon={Users} title="1. Refer" delay={0}>
            Share your unique referral link or code. Landlords enter it once, at registration.
          </FeatureCard>
          <FeatureCard icon={TrendingUp} title="2. They pay, you earn" accent="third" delay={80}>
            Every time they pay their subscription, you earn {rate}% — for their first {months} paid months.
          </FeatureCard>
          <FeatureCard icon={Wallet} title="3. Withdraw anytime" delay={160}>
            Once your balance clears the minimum, request a withdrawal straight to your M-Pesa number.
          </FeatureCard>
        </div>
      </Section>

      {/* Signup form */}
      <Section className="!pt-4" innerClassName="max-w-xl">
        {submitted ? (
          <Reveal className="glass p-8 text-center">
            <CheckCircle2 className="mx-auto h-10 w-10 text-emerald-400" />
            <h2 className="mt-4 text-xl font-light text-white">Application received</h2>
            <p className="mt-2 text-sm text-white/60">
              Check your email to verify your address. Once verified, our team will review and approve your
              account — you'll be notified and your referral code will go live.
            </p>
            <Link to={AUTH_ROUTES.login} className="mt-6 inline-block text-sm text-secondary hover:underline">
              Go to login →
            </Link>
          </Reveal>
        ) : (
          <Reveal className="glass p-8">
            <h2 className="text-center text-xl font-light text-white">Become an affiliate</h2>
            <form onSubmit={handleSubmit} className="mt-6 space-y-4">
              <Input
                label="Full name"
                leftIcon={<User className="h-4 w-4" />}
                value={form.full_name}
                onChange={update("full_name")}
                error={errors.full_name}
                required
              />
              <Input
                label="Email"
                type="email"
                leftIcon={<Mail className="h-4 w-4" />}
                value={form.email}
                onChange={update("email")}
                error={errors.email}
                required
              />
              <Input
                label="Phone"
                leftIcon={<Phone className="h-4 w-4" />}
                value={form.phone}
                onChange={update("phone")}
                error={errors.phone}
                required
              />
              <Input
                label="Password"
                type="password"
                leftIcon={<Lock className="h-4 w-4" />}
                value={form.password}
                onChange={update("password")}
                error={errors.password}
                required
              />
              <Button type="submit" className="w-full" isLoading={isLoading} disabled={!programActive}>
                Create affiliate account
              </Button>
            </form>
            <p className="mt-6 text-center text-sm text-white/50">
              Already an affiliate?{" "}
              <Link to={AUTH_ROUTES.login} className="text-secondary hover:underline">
                Log in
              </Link>
            </p>
          </Reveal>
        )}
      </Section>
    </div>
  );
}
