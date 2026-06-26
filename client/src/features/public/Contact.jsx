import { useState } from "react";
import { Mail, Phone, MapPin } from "lucide-react";
import Input from "@/components/ui/Input";
import Textarea from "@/components/ui/Textarea";
import Button from "@/components/ui/Button";
import { toast } from "@/components/ui/Toast";
import { isRequired, isValidEmail } from "@/utils/validators";

export default function Contact() {
  const [form, setForm] = useState({ name: "", email: "", message: "" });
  const [errors, setErrors] = useState({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  const update = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const handleSubmit = (e) => {
    e.preventDefault();
    const nextErrors = {};
    if (!isRequired(form.name)) nextErrors.name = "Your name is required";
    if (!isRequired(form.email) || !isValidEmail(form.email)) nextErrors.email = "Enter a valid email";
    if (!isRequired(form.message)) nextErrors.message = "Tell us a little about your portfolio";
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;

    setIsSubmitting(true);
    setTimeout(() => {
      setIsSubmitting(false);
      setForm({ name: "", email: "", message: "" });
      toast("Thanks — we'll be in touch shortly.", { type: "success" });
    }, 600);
  };

  return (
    <section className="mx-auto max-w-5xl px-6 py-24">
      <h1 className="animate-fade-in-up text-center text-3xl font-light text-white">Get in touch</h1>
      <div className="mt-14 grid gap-8 lg:grid-cols-[1fr_1.2fr]">
        <div className="animate-fade-in-up space-y-5">
          <div className="glass flex items-center gap-3 p-4">
            <Mail className="h-5 w-5 text-secondary" />
            <span className="text-sm text-white/70">hello@sahilpay.com</span>
          </div>
          <div className="glass flex items-center gap-3 p-4">
            <Phone className="h-5 w-5 text-secondary" />
            <span className="text-sm text-white/70">+254 700 000 000</span>
          </div>
          <div className="glass flex items-center gap-3 p-4">
            <MapPin className="h-5 w-5 text-secondary" />
            <span className="text-sm text-white/70">Nairobi, Kenya</span>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="glass animate-fade-in-up space-y-4 p-8" style={{ animationDelay: "100ms" }}>
          <Input label="Name" value={form.name} onChange={update("name")} error={errors.name} required />
          <Input label="Email" type="email" value={form.email} onChange={update("email")} error={errors.email} required />
          <Textarea label="Message" rows={5} value={form.message} onChange={update("message")} error={errors.message} required />
          <Button type="submit" className="w-full" isLoading={isSubmitting}>
            Send message
          </Button>
        </form>
      </div>
    </section>
  );
}
