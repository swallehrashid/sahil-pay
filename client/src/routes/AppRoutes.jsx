import { lazy, Suspense, useState } from "react";
import { Routes, Route, Navigate, Outlet } from "react-router-dom";
import { Menu } from "lucide-react";
import ProtectedRoutes, { RouteLoader } from "@/components/ProtectedRoutes";
import ErrorBoundary from "@/components/feedback/ErrorBoundary";
import NotFound from "@/components/feedback/NotFound";
import PublicLayout from "@/components/layout/PublicLayout";
import LandlordNavbar from "@/features/landlord/components/LandlordNavbar";
import LandlordSidebar from "@/features/landlord/components/LandlordSidebar";
import TeamMemberNavbar from "@/features/teamMember/components/TeamMemberNavbar";
import TeamMemberSidebar from "@/features/teamMember/components/TeamMemberSidebar";
import AdminNavbar from "@/features/admin/components/AdminNavbar";
import AdminSidebar from "@/features/admin/components/AdminSidebar";
import TenantNavbar from "@/features/tenant/components/TenantNavbar";
import { USER_ROLES } from "@/utils/constants";
import { PUBLIC_ROUTES, AUTH_ROUTES, LANDLORD_ROUTES, TEAM_ROUTES, TENANT_ROUTES, ADMIN_ROUTES, NOT_FOUND_ROUTE } from "@/config/routePaths";

// ---- Public ----
const Home = lazy(() => import("@/features/public/Home"));
const About = lazy(() => import("@/features/public/About"));
const Features = lazy(() => import("@/features/public/Features"));
const Pricing = lazy(() => import("@/features/public/Pricing"));
const Contact = lazy(() => import("@/features/public/Contact"));
const FAQ = lazy(() => import("@/features/public/FAQ"));
const PrivacyPolicy = lazy(() => import("@/features/public/PrivacyPolicy"));
const TermsOfService = lazy(() => import("@/features/public/TermsOfService"));

// ---- Auth ----
const Login = lazy(() => import("@/features/auth/Login"));
const LandlordRegistration = lazy(() => import("@/features/auth/LandlordRegistration"));
const VerifyEmail = lazy(() => import("@/features/auth/VerifyEmail"));
const ForgotPassword = lazy(() => import("@/features/auth/ForgotPassword"));
const ResetPassword = lazy(() => import("@/features/auth/ResetPassword"));
const TeamActivation = lazy(() => import("@/features/auth/TeamActivation"));
const TenantOtpLogin = lazy(() => import("@/features/auth/TenantOtpLogin"));

// ---- Landlord (and re-mounted by Team Member under permission guards) ----
const LandlordDashboard = lazy(() => import("@/features/landlord/LandlordDashboard"));
const PropertiesPage = lazy(() => import("@/features/landlord/properties/PropertiesPage"));
const UnitsPage = lazy(() => import("@/features/landlord/units/UnitsPage"));
const TenantsPage = lazy(() => import("@/features/landlord/tenants/TenantsPage"));
const DeletedTenants = lazy(() => import("@/features/landlord/tenants/DeletedTenants"));
const TenantTransactions = lazy(() => import("@/features/landlord/tenants/TenantTransactions"));
const InvoicesPage = lazy(() => import("@/features/landlord/invoices/InvoicesPage"));
const PaymentsPage = lazy(() => import("@/features/landlord/payments/PaymentsPage"));
const BankStatementReview = lazy(() => import("@/features/landlord/payments/BankStatementReview"));
const ExpensesPage = lazy(() => import("@/features/landlord/expenses/ExpensesPage"));
const UtilitiesPage = lazy(() => import("@/features/landlord/utilities/UtilitiesPage"));
const MaintenancePage = lazy(() => import("@/features/landlord/maintenance/MaintenancePage"));
const PropertyGroupsPage = lazy(() => import("@/features/landlord/groups/PropertyGroupsPage"));
const StatementsPage = lazy(() => import("@/features/landlord/reports/StatementsPage"));
const InsightsPage = lazy(() => import("@/features/landlord/reports/InsightsPage"));
const CommunicationsPage = lazy(() => import("@/features/landlord/communications/CommunicationsPage"));

// Landlord settings
const SettingsLayout = lazy(() => import("@/features/landlord/settings/SettingsLayout"));
const GeneralSettings = lazy(() => import("@/features/landlord/settings/GeneralSettings"));
const BackupSettings = lazy(() => import("@/features/landlord/settings/BackupSettings"));
const AlertSettings = lazy(() => import("@/features/landlord/settings/AlertSettings"));
const AccountSettings = lazy(() => import("@/features/landlord/settings/AccountSettings"));
const DocumentTemplates = lazy(() => import("@/features/landlord/settings/DocumentTemplates"));
const TeamManagement = lazy(() => import("@/features/landlord/settings/TeamManagement"));
const BillingSettings = lazy(() => import("@/features/landlord/settings/BillingSettings"));
const MpesaStatus = lazy(() => import("@/features/landlord/settings/MpesaStatus"));
const AuditTrail = lazy(() => import("@/features/landlord/settings/AuditTrail"));
const ImpersonationRequests = lazy(() => import("@/features/landlord/settings/ImpersonationRequests"));

// ---- Team Member (own pages only — data pages reuse the landlord components above) ----
const TeamMemberDashboard = lazy(() => import("@/features/teamMember/TeamMemberDashboard"));
const TeamMemberProfile = lazy(() => import("@/features/teamMember/TeamMemberProfile"));

// ---- Tenant ----
const TenantDashboard = lazy(() => import("@/features/tenant/TenantDashboard"));
const TenantPayments = lazy(() => import("@/features/tenant/TenantPayments"));
const TenantStatement = lazy(() => import("@/features/tenant/TenantStatement"));
const TenantMaintenance = lazy(() => import("@/features/tenant/TenantMaintenance"));
const TenantProfile = lazy(() => import("@/features/tenant/TenantProfile"));

// ---- Admin ----
const AdminDashboard = lazy(() => import("@/features/admin/AdminDashboard"));
const LandlordsManagement = lazy(() => import("@/features/admin/LandlordsManagement"));
const LandlordDetail = lazy(() => import("@/features/admin/LandlordDetail"));
const PricingPackages = lazy(() => import("@/features/admin/PricingPackages"));
const TrialConfig = lazy(() => import("@/features/admin/TrialConfig"));
const Impersonation = lazy(() => import("@/features/admin/Impersonation"));
const MasterAuditLogs = lazy(() => import("@/features/admin/MasterAuditLogs"));

// Wraps a lazy page in the branded glass loader as its Suspense fallback.
function withSuspense(Component) {
  return (
    <Suspense fallback={<RouteLoader />}>
      <Component />
    </Suspense>
  );
}

function MobileTopBar({ onOpen }) {
  return (
    <header className="glass sticky top-4 z-20 mx-4 flex items-center gap-3 rounded-2xl px-4 py-3 lg:hidden">
      <button onClick={onOpen} className="rounded-lg p-2 text-white/70 hover:bg-white/10">
        <Menu className="h-5 w-5" />
      </button>
      <span className="font-light tracking-wide text-white">SahilPay</span>
    </header>
  );
}

// No dedicated per-portal layout files exist in the structure beyond the generic
// DashboardLayout — these three portals each have their own Sidebar+Navbar pairing,
// so the shell is composed here rather than forcing them through the generic layout.
function LandlordLayout() {
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);
  return (
    <div className="app-bg flex min-h-screen">
      <LandlordSidebar isMobileOpen={isMobileNavOpen} onCloseMobile={() => setIsMobileNavOpen(false)} />
      <div className="flex min-h-screen flex-1 flex-col lg:pl-64">
        <MobileTopBar onOpen={() => setIsMobileNavOpen(true)} />
        <LandlordNavbar />
        <main className="flex-1 p-4 md:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function TeamMemberLayout() {
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);
  return (
    <div className="app-bg flex min-h-screen">
      <TeamMemberSidebar isMobileOpen={isMobileNavOpen} onCloseMobile={() => setIsMobileNavOpen(false)} />
      <div className="flex min-h-screen flex-1 flex-col lg:pl-64">
        <MobileTopBar onOpen={() => setIsMobileNavOpen(true)} />
        <TeamMemberNavbar />
        <main className="flex-1 p-4 md:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function AdminLayout() {
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);
  return (
    <div className="app-bg flex min-h-screen">
      <AdminSidebar isMobileOpen={isMobileNavOpen} onCloseMobile={() => setIsMobileNavOpen(false)} />
      <div className="flex min-h-screen flex-1 flex-col lg:pl-64">
        <MobileTopBar onOpen={() => setIsMobileNavOpen(true)} />
        <AdminNavbar />
        <main className="flex-1 p-4 md:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function TenantLayout() {
  return (
    <div className="app-bg min-h-screen">
      <TenantNavbar />
      <main className="p-4 pb-10 sm:p-6">
        <Outlet />
      </main>
    </div>
  );
}

export default function AppRoutes() {
  return (
    <ErrorBoundary>
      <Routes>
        {/* Public / marketing */}
        <Route element={<PublicLayout />}>
          <Route path={PUBLIC_ROUTES.home} element={withSuspense(Home)} />
          <Route path={PUBLIC_ROUTES.about} element={withSuspense(About)} />
          <Route path={PUBLIC_ROUTES.features} element={withSuspense(Features)} />
          <Route path={PUBLIC_ROUTES.pricing} element={withSuspense(Pricing)} />
          <Route path={PUBLIC_ROUTES.contact} element={withSuspense(Contact)} />
          <Route path={PUBLIC_ROUTES.faq} element={withSuspense(FAQ)} />
          <Route path={PUBLIC_ROUTES.privacy} element={withSuspense(PrivacyPolicy)} />
          <Route path={PUBLIC_ROUTES.terms} element={withSuspense(TermsOfService)} />
        </Route>

        {/* Auth — pages wrap themselves in <AuthLayout>, so no shared layout route here */}
        <Route path={AUTH_ROUTES.login} element={withSuspense(Login)} />
        <Route path={AUTH_ROUTES.register} element={withSuspense(LandlordRegistration)} />
        <Route path={AUTH_ROUTES.verifyEmail} element={withSuspense(VerifyEmail)} />
        <Route path={AUTH_ROUTES.forgotPassword} element={withSuspense(ForgotPassword)} />
        <Route path={AUTH_ROUTES.resetPassword} element={withSuspense(ResetPassword)} />
        <Route path={AUTH_ROUTES.teamActivate} element={withSuspense(TeamActivation)} />
        <Route path={AUTH_ROUTES.tenantLogin} element={withSuspense(TenantOtpLogin)} />

        {/* Landlord / Property Manager portal */}
        <Route element={<ProtectedRoutes allowedRoles={[USER_ROLES.LANDLORD, USER_ROLES.PROPERTY_MANAGER]} />}>
          <Route path={LANDLORD_ROUTES.root} element={<LandlordLayout />}>
            <Route index element={<Navigate to="dashboard" replace />} />
            <Route path="dashboard" element={withSuspense(LandlordDashboard)} />
            <Route path="properties" element={withSuspense(PropertiesPage)} />
            <Route path="units" element={withSuspense(UnitsPage)} />
            <Route path="tenants" element={withSuspense(TenantsPage)} />
            <Route path="tenants/deleted" element={withSuspense(DeletedTenants)} />
            <Route path="tenants/:id/transactions" element={withSuspense(TenantTransactions)} />
            <Route path="invoices" element={withSuspense(InvoicesPage)} />
            <Route path="payments" element={withSuspense(PaymentsPage)} />
            <Route path="payments/bank-statement/:id" element={withSuspense(BankStatementReview)} />
            <Route path="expenses" element={withSuspense(ExpensesPage)} />
            <Route path="utilities" element={withSuspense(UtilitiesPage)} />
            <Route path="maintenance" element={withSuspense(MaintenancePage)} />
            <Route path="groups" element={withSuspense(PropertyGroupsPage)} />
            <Route path="reports/statements" element={withSuspense(StatementsPage)} />
            <Route path="reports/insights" element={withSuspense(InsightsPage)} />
            <Route path="communications" element={withSuspense(CommunicationsPage)} />

            <Route path="settings" element={withSuspense(SettingsLayout)}>
              <Route index element={<Navigate to="general" replace />} />
              <Route path="general" element={withSuspense(GeneralSettings)} />
              <Route path="backup" element={withSuspense(BackupSettings)} />
              <Route path="alerts" element={withSuspense(AlertSettings)} />
              <Route path="account" element={withSuspense(AccountSettings)} />
              <Route path="documents" element={withSuspense(DocumentTemplates)} />
              <Route path="team" element={withSuspense(TeamManagement)} />
              <Route path="billing" element={withSuspense(BillingSettings)} />
              <Route path="mpesa" element={withSuspense(MpesaStatus)} />
              <Route path="audit" element={withSuspense(AuditTrail)} />
              <Route path="impersonation-requests" element={withSuspense(ImpersonationRequests)} />
            </Route>
          </Route>
        </Route>

        {/* Team Member portal — re-mounts the landlord module pages under permission guards */}
        <Route element={<ProtectedRoutes allowedRoles={[USER_ROLES.TEAM_MEMBER]} />}>
          <Route path={TEAM_ROUTES.root} element={<TeamMemberLayout />}>
            <Route index element={<Navigate to="dashboard" replace />} />
            <Route path="dashboard" element={withSuspense(TeamMemberDashboard)} />
            <Route path="profile" element={withSuspense(TeamMemberProfile)} />

            <Route element={<ProtectedRoutes requiredPermission={{ module: "properties", level: "view" }} />}>
              <Route path="properties" element={withSuspense(PropertiesPage)} />
            </Route>
            <Route element={<ProtectedRoutes requiredPermission={{ module: "units", level: "view" }} />}>
              <Route path="units" element={withSuspense(UnitsPage)} />
            </Route>
            <Route element={<ProtectedRoutes requiredPermission={{ module: "tenants", level: "view" }} />}>
              <Route path="tenants" element={withSuspense(TenantsPage)} />
              <Route path="tenants/deleted" element={withSuspense(DeletedTenants)} />
              <Route path="tenants/:id/transactions" element={withSuspense(TenantTransactions)} />
            </Route>
            <Route element={<ProtectedRoutes requiredPermission={{ module: "invoices", level: "view" }} />}>
              <Route path="invoices" element={withSuspense(InvoicesPage)} />
            </Route>
            <Route element={<ProtectedRoutes requiredPermission={{ module: "payments", level: "view" }} />}>
              <Route path="payments" element={withSuspense(PaymentsPage)} />
              <Route path="payments/bank-statement/:id" element={withSuspense(BankStatementReview)} />
            </Route>
            <Route path="expenses" element={withSuspense(ExpensesPage)} />
            <Route element={<ProtectedRoutes requiredPermission={{ module: "utilities", level: "view" }} />}>
              <Route path="utilities" element={withSuspense(UtilitiesPage)} />
            </Route>
            <Route path="maintenance" element={withSuspense(MaintenancePage)} />
            <Route path="groups" element={withSuspense(PropertyGroupsPage)} />
            <Route path="reports/statements" element={withSuspense(StatementsPage)} />
            <Route path="reports/insights" element={withSuspense(InsightsPage)} />
            <Route element={<ProtectedRoutes requiredPermission={{ module: "messages", level: "view" }} />}>
              <Route path="communications" element={withSuspense(CommunicationsPage)} />
            </Route>
          </Route>
        </Route>

        {/* Tenant portal */}
        <Route element={<ProtectedRoutes allowedRoles={[USER_ROLES.TENANT]} />}>
          <Route path={TENANT_ROUTES.root} element={<TenantLayout />}>
            <Route index element={<Navigate to="dashboard" replace />} />
            <Route path="dashboard" element={withSuspense(TenantDashboard)} />
            <Route path="pay" element={withSuspense(TenantPayments)} />
            <Route path="statement" element={withSuspense(TenantStatement)} />
            <Route path="maintenance" element={withSuspense(TenantMaintenance)} />
            <Route path="profile" element={withSuspense(TenantProfile)} />
          </Route>
        </Route>

        {/* System Admin portal */}
        <Route element={<ProtectedRoutes allowedRoles={[USER_ROLES.SYSTEM_ADMIN]} />}>
          <Route path={ADMIN_ROUTES.root} element={<AdminLayout />}>
            <Route index element={<Navigate to="dashboard" replace />} />
            <Route path="dashboard" element={withSuspense(AdminDashboard)} />
            <Route path="landlords" element={withSuspense(LandlordsManagement)} />
            <Route path="landlords/:id" element={withSuspense(LandlordDetail)} />
            <Route path="pricing" element={withSuspense(PricingPackages)} />
            <Route path="trials" element={withSuspense(TrialConfig)} />
            <Route path="impersonation" element={withSuspense(Impersonation)} />
            <Route path="audit" element={withSuspense(MasterAuditLogs)} />
          </Route>
        </Route>

        <Route path={NOT_FOUND_ROUTE} element={<NotFound />} />
      </Routes>
    </ErrorBoundary>
  );
}
