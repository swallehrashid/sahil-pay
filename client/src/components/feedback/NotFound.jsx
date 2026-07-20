import { Link } from "react-router-dom";
import { Compass } from "lucide-react";
import Button from "@/components/ui/Button";
import { PUBLIC_ROUTES } from "@/config/routePaths";

export default function NotFound() {
  return (
    <div className="app-bg flex min-h-screen items-center justify-center p-6">
      <div className="glass max-w-md animate-scale-in p-10 text-center">
        <Compass className="mx-auto mb-4 h-10 w-10 text-secondary" />
        <p className="text-sm font-medium uppercase tracking-widest text-white/40">404</p>
        <h1 className="mt-2 text-2xl font-light text-white">Page not found</h1>
        <p className="mt-2 text-sm text-white/50">The page you're looking for doesn't exist or has moved.</p>
        <Link to={PUBLIC_ROUTES.home}>
          <Button className="mt-6">Back to home</Button>
        </Link>
      </div>
    </div>
  );
}
