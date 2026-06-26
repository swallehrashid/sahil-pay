import { Component } from "react";
import { AlertTriangle } from "lucide-react";
import Button from "@/components/ui/Button";

// Catches render errors per route so one broken page never blanks the whole app.
export default class ErrorBoundary extends Component {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    console.error("ErrorBoundary caught:", error, info);
  }

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div className="app-bg flex min-h-screen items-center justify-center p-6">
        <div className="glass max-w-md animate-scale-in p-8 text-center">
          <AlertTriangle className="mx-auto mb-4 h-10 w-10 text-secondary" />
          <h2 className="text-lg font-medium text-white">Something went wrong</h2>
          <p className="mt-2 text-sm text-white/50">
            An unexpected error occurred while rendering this page. Try reloading — if it keeps
            happening, contact support.
          </p>
          <Button className="mt-6" onClick={() => window.location.reload()}>
            Reload page
          </Button>
        </div>
      </div>
    );
  }
}
