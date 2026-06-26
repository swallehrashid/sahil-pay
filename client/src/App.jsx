import AppRoutes from "./routes/AppRoutes";
import ToastViewport from "./components/ui/Toast";
import ErrorBoundary from "./components/feedback/ErrorBoundary";

function App() {
  return (
    <ErrorBoundary>
      <AppRoutes />
      <ToastViewport />
    </ErrorBoundary>
  );
}

export default App;
