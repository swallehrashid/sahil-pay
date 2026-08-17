import { useEffect } from "react";
import { Outlet } from "react-router-dom";
import PublicNavbar from "@/features/public/components/PublicNavbar";
import Footer from "@/components/Footer";
import { captureReferralFromUrl } from "@/utils/referralStorage";
import { ORGANIZATION_JSON_LD } from "@/features/public/useSeo";

export default function PublicLayout() {
  // Capture ?ref=CODE on every public page — a visitor may land on Pricing or
  // Home via a shared affiliate link, then browse before registering.
  useEffect(() => {
    captureReferralFromUrl();
  }, []);

  // The sitewide publisher identity — who runs this site, the logo, and how to
  // reach us. It belongs on EVERY public page, not just one, which is why it
  // lives in the layout rather than in a page's own useSeo() call. It was
  // written months ago and exported, but nothing ever rendered it.
  useEffect(() => {
    const ID = "organization-jsonld";
    let tag = document.head.querySelector(`script[data-seo="${ID}"]`);
    if (!tag) {
      tag = document.createElement("script");
      tag.type = "application/ld+json";
      tag.dataset.seo = ID;
      document.head.appendChild(tag);
    }
    tag.textContent = JSON.stringify(ORGANIZATION_JSON_LD);
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
