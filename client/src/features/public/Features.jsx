import { Building2, Receipt, Wallet, Wrench, MessageSquare, ShieldCheck } from "lucide-react";

const GROUPS = [
  { icon: Building2, title: "Property & Tenancy", items: ["Property groups, properties & units", "Full tenant lifecycle, with shift history", "Lease expiry alerts"] },
  { icon: Receipt, title: "Invoicing", items: ["Rent, utility, penalty, custom & recurring invoices", "Bulk generation", "PDF statements"] },
  { icon: Wallet, title: "Payments", items: ["M-Pesa, bank statement & manual recording", "Multi-invoice allocation", "Co-pilot SMS forwarding"] },
  { icon: Wrench, title: "Operations", items: ["Expenses & recurring expenses", "Utility readings → invoices", "Maintenance requests & linked expenses"] },
  { icon: MessageSquare, title: "Communications", items: ["SMS, WhatsApp & email templates", "Delivery tracking", "Tenant document templates"] },
  { icon: ShieldCheck, title: "Governance", items: ["Role & permission matrix for teams", "Full audit trail", "Scoped backups (Excel/PDF)"] },
];

export default function Features() {
  return (
    <section className="mx-auto max-w-6xl px-6 py-24">
      <h1 className="animate-fade-in-up text-center text-3xl font-light text-white">Built for the whole portfolio</h1>
      <p className="mx-auto mt-3 max-w-xl animate-fade-in-up text-center text-white/60" style={{ animationDelay: "80ms" }}>
        Every module your landlord, team and tenants need — under one roof.
      </p>
      <div className="mt-14 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {GROUPS.map((group, index) => (
          <div key={group.title} className="glass card-hover animate-fade-in-up p-6" style={{ animationDelay: `${index * 80}ms` }}>
            <span className="inline-flex rounded-xl bg-third/15 p-3 text-third-100">
              <group.icon className="h-5 w-5" />
            </span>
            <h3 className="mt-4 text-base font-medium text-white">{group.title}</h3>
            <ul className="mt-3 space-y-1.5 text-sm text-white/50">
              {group.items.map((item) => (
                <li key={item}>• {item}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
