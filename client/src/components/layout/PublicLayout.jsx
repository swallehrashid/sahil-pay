import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import PublicNavbar from "@/features/public/components/PublicNavbar";
import Footer from "@/components/Footer";
import { captureReferralFromUrl } from "@/utils/referralStorage";

export default function PublicLayout() {
  // Capture ?ref=CODE on every public page — a visitor may land on Pricing or
  // Home via a shared affiliate link, then browse before registering.
  useEffect(() => {
    captureReferralFromUrl();
  }, []);

  return (
    <div className="app-bg flex min-h-screen flex-col scroll-smooth">
      <PublicNavbar />
      <main className="flex-1">
        <Outlet />
      </main>
      <Footer />
    </div>
  );
}
