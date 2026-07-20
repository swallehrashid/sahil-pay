import { useState } from "react";
import { Menu } from "lucide-react";
import Sidebar from "./Sidebar";
import SahilPayLogo from "@/components/branding/SahilPayLogo";

// Sidebar + topbar shell shared by Landlord / Team Member / Admin. Hosts the app-bg gradient.
export default function DashboardLayout({ navItems, sidebarHeader, sidebarFooter, navbar, children }) {
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);

  return (
    <div className="app-bg flex min-h-screen">
      <Sidebar
        items={navItems}
        header={sidebarHeader}
        footer={sidebarFooter}
        isMobileOpen={isMobileNavOpen}
        onCloseMobile={() => setIsMobileNavOpen(false)}
      />
      <div className="flex min-h-screen min-w-0 flex-1 flex-col lg:pl-64">
        <header className="glass sticky top-4 z-20 mx-4 flex items-center gap-3 rounded-2xl px-4 py-3 lg:hidden">
          <button onClick={() => setIsMobileNavOpen(true)} className="rounded-lg p-2 text-white/70 hover:bg-white/10">
            <Menu className="h-5 w-5" />
          </button>
          <SahilPayLogo withSlogan={false} className="h-6 text-white" />
        </header>
        {navbar}
        <main className="min-w-0 flex-1 p-4 md:p-8">{children}</main>
      </div>
    </div>
  );
}
