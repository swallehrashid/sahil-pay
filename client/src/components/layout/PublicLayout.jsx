import { Outlet } from "react-router-dom";
import PublicNavbar from "@/features/public/components/PublicNavbar";
import Footer from "@/components/Footer";

export default function PublicLayout() {
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
