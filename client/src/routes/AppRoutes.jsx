import { lazy, Suspense, useState } from "react";
import { Routes, Route, Navigate, Outlet } from "react-router-dom";
import { Menu } from "lucide-react";
import ProtectedRoutes, { RouteLoader } from "@/components/ProtectedRoutes";
import SahilPayLogo from "@/components/branding/SahilPayLogo";
import ErrorBoundary from "@/components/feedback/ErrorBoundary";
import NotFound from "@/components/feedback/NotFound";
import PublicLayout from "@/components/layout/PublicLayout";
import LandlordNavbar from "@/features/landlord/components/LandlordNavbar";
import LandlordSidebar from "@/features/landlord/components/LandlordSidebar";
import TourProvider from "@/features/landlord/tutorials/TourProvider";
import TeamMemberNavbar from "@/features/teamMember/components/TeamMemberNavbar";
import TeamMemberSidebar from "@/features/teamMember/components/TeamMemberSidebar";
import TeamMemberViewLogger from "@/features/teamMember/TeamMemberViewLogger";
import AdminNavbar from "@/features/admin/components/AdminNavbar";
import AdminSidebar from "@/features/admin/components/AdminSidebar";
import AdminImpersonationBanner from "@/features/admin/components/AdminImpersonationBanner";
import DemoModeBanner from "@/features/landlord/components/DemoModeBanner";
import DemoBlockedPage from "@/features/landlord/components/DemoBlockedPage";
import { getDemoMode } from "@/utils/demoStorage";
import TenantNavbar from "@/features/tenant/components/TenantNavbar";
import AffiliateNavbar from "@/features/affiliate/components/AffiliateNavbar";
import AffiliateSidebar from "@/features/affiliate/components/AffiliateSidebar";
import { USER_ROLES } from "@/utils/constants";
import { PUBLIC_ROUTES, AUTH_ROUTES, LANDLORD_ROUTES, TEAM_ROUTES, TENANT_ROUTES, ADMIN_ROUTES, AFFILIATE_ROUTES, NOT_FOUND_ROUTE } from "@/config/routePaths";

// ---- Public ----
const Home = lazy(() => import("@/features/public/Home"));
const About = lazy(() => import("@/features/public/About"));
const Features = lazy(() => import("@/features/public/Features"));
const Pricing = lazy(() => import("@/features/public/Pricing"));
const Contact = lazy(() => import("@/features/public/Contact"));
const FAQ = lazy(() => import("@/features/public/FAQ"));
const PrivacyPolicy = lazy(() => import("@/features/public/PrivacyPolicy"));
const TermsOfService = lazy(() => import("@/features/public/TermsOfService"));
const AffiliateSignup = lazy(() => import("@/features/public/AffiliateSignup"));

// ---- Auth ----
const Login = lazy(() => import("@/features/auth/Login"));
const LandlordRegistration = lazy(() => import("@/features/auth/LandlordRegistration"));
const VerifyEmail = lazy(() => import("@/features/auth/VerifyEmail"));
const ForgotPassword = lazy(() => import("@/features/auth/ForgotPassword"));
const ResetPassword = lazy(() => import("@/features/auth/ResetPassword"));
const TeamActivation = lazy(() => import("@/features/auth/TeamActivation"));
const TenantOtpLogin = lazy(() => import("@/features/auth/TenantOtpLogin"));
const ChangePassword = lazy(() => import("@/features/auth/ChangePassword"));

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
const TenantMessagesInbox = lazy(() => import("@/features/landlord/messages/TenantMessagesInbox"));
const TutorialsPage = lazy(() => import("@/features/landlord/tutorials/TutorialsPage"));

// ---- Notifications (shared across all four portals) ----
const NotificationsPage = lazy(() => import("@/features/notifications/NotificationsPage"));
const SendNotificationLandlord = lazy(() => import("@/features/notifications/SendNotificationLandlord"));
const SendNotificationAdmin = lazy(() => import("@/features/notifications/SendNotificationAdmin"));

// Landlord settings
const SettingsLayout = lazy(() => import("@/features/landlord/settings/SettingsLayout"));
const GeneralSettings = lazy(() => import("@/features/landlord/settings/GeneralSettings"));
const BackupSettings = lazy(() => import("@/features/landlord/settings/BackupSettings"));
const AlertSettings = lazy(() => import("@/features/landlord/settings/AlertSettings"));
const AccountSettings = lazy(() => import("@/features/landlord/settings/AccountSettings"));
const DocumentTemplates = lazy(() => import("@/features/landlord/settings/DocumentTemplates"));
const TeamManagement = lazy(() => import("@/features/landlord/settings/TeamManagement"));
const BillingSettings = lazy(() => import("@/features/landlord/settings/BillingSettings"));
const SmsProviderSettings = lazy(() => import("@/features/landlord/settings/SmsProviderSettings"));
const MpesaStatus = lazy(() => import("@/features/landlord/settings/MpesaStatus"));
const CopilotSettings = lazy(() => import("@/features/landlord/settings/CopilotSettings"));
const AuditTrail = lazy(() => import("@/features/landlord/settings/AuditTrail"));
const ImpersonationRequests = lazy(() => import("@/features/landlord/settings/ImpersonationRequests"));

// ---- Team Member (own pages only — data pages reuse the landlord components above) ----
const TeamMemberDashboard = lazy(() => import("@/features/teamMember/TeamMemberDashboard"));
const TeamMemberProfile = lazy(() => import("@/features/teamMember/TeamMemberProfile"));

// ---- Affiliate ----
const AffiliateDashboard = lazy(() => import("@/features/affiliate/AffiliateDashboard"));
const AffiliateReferrals = lazy(() => import("@/features/affiliate/AffiliateReferrals"));
const AffiliateEarnings = lazy(() => import("@/features/affiliate/AffiliateEarnings"));
const AffiliateWithdrawals = lazy(() => import("@/features/affiliate/AffiliateWithdrawals"));
const AffiliateProfile = lazy(() => import("@/features/affiliate/AffiliateProfile"));

// ---- Tenant ----
const TenantDashboard = lazy(() => import("@/features/tenant/TenantDashboard"));
const TenantPayments = lazy(() => import("@/features/tenant/TenantPayments"));
const TenantStatement = lazy(() => import("@/features/tenant/TenantStatement"));
const TenantMaintenance = lazy(() => import("@/features/tenant/TenantMaintenance"));
const TenantMessages = lazy(() => import("@/features/tenant/TenantMessages"));
const TenantProfile = lazy(() => import("@/features/tenant/TenantProfile"));

// ---- Admin ----
const AdminDashboard = lazy(() => import("@/features/admin/AdminDashboard"));
const LandlordsManagement = lazy(() => import("@/features/admin/LandlordsManagement"));
const LandlordDetail = lazy(() => import("@/features/admin/LandlordDetail"));
const AdminUnits = lazy(() => import("@/features/admin/AdminUnits"));
const UnitDetail = lazy(() => import("@/features/admin/UnitDetail"));
const AdminTenants = lazy(() => import("@/features/admin/AdminTenants"));
const TenantDetail = lazy(() => import("@/features/admin/TenantDetail"));
const AdminTeamMembers = lazy(() => import("@/features/admin/AdminTeamMembers"));
const TeamMemberDetail = lazy(() => import("@/features/admin/TeamMemberDetail"));
const AdminProperties = lazy(() => import("@/features/admin/AdminProperties"));
const PropertyDetail = lazy(() => import("@/features/admin/PropertyDetail"));
const PricingPackages = lazy(() => import("@/features/admin/PricingPackages"));
const PackageDetail = lazy(() => import("@/features/admin/PackageDetail"));
const SmsManagement = lazy(() => import("@/features/admin/SmsManagement"));
const AdminBilling = lazy(() => import("@/features/admin/AdminBilling"));
const CopilotManagement = lazy(() => import("@/features/admin/CopilotManagement"));
const TrialConfig = lazy(() => import("@/features/admin/TrialConfig"));
const Impersonation = lazy(() => import("@/features/admin/Impersonation"));
const MasterAuditLogs = lazy(() => import("@/features/admin/MasterAuditLogs"));
const AffiliatesManagement = lazy(() => import("@/features/admin/AffiliatesManagement"));
const AdminAffiliateDetail = lazy(() => import("@/features/admin/AdminAffiliateDetail"));
const AffiliateWithdrawalsQueue = lazy(() => import("@/features/admin/AffiliateWithdrawalsQueue"));
const AffiliateReports = lazy(() => import("@/features/admin/AffiliateReports"));
const AffiliateProgramSettings = lazy(() => import("@/features/admin/AffiliateProgramSettings"));

// Wraps a lazy page in the branded glass loader as its Suspense fallback.
function withSuspense(Component) {
  return (
    <Suspense fallback={<RouteLoader />}>
      <Component />
    </Suspense>
  );
}

// Account-level settings pages are hidden from the nav in demo mode
// (SettingsLayout.jsx) — this is the belt-and-braces guard for direct
// navigation (DEMO_MODE_SPEC.md §5.6). Checked at render time (not just once)
// so entering/exiting demo mode without a full reload still takes effect.
function withDemoBlock(Component) {
  function Guarded() {
    if (getDemoMode()?.active) return <DemoBlockedPage />;
    return <Component />;
  }
  return (
    <Suspense fallback={<RouteLoader />}>
      <Guarded />
    </Suspense>
  );
}

function MobileTopBar({ onOpen }) {
  return (
    <header className="glass sticky top-4 z-20 mx-4 flex items-center gap-3 rounded-2xl px-4 py-3 lg:hidden">
      <button onClick={onOpen} className="rounded-lg p-2 text-white/70 hover:bg-white/10">
        <Menu className="h-5 w-5" />
      </button>
      <SahilPayLogo withSlogan={false} className="h-6 text-white" />
    </header>
  );
}

// No dedicated per-portal layout files exist in the structure beyond the generic
// DashboardLayout — these three portals each have their own Sidebar+Navbar pairing,
// so the shell is composed here rather than forcing them through the generic layout.
function LandlordLayout() {
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);
  return (
    <TourProvider>
      <div className="app-bg flex min-h-screen">
        <LandlordSidebar isMobileOpen={isMobileNavOpen} onCloseMobile={() => setIsMobileNavOpen(false)} />
        <div className="flex min-h-screen min-w-0 flex-1 flex-col lg:pl-64">
          <MobileTopBar onOpen={() => setIsMobileNavOpen(true)} />
          <LandlordNavbar />
          <main className="min-w-0 flex-1 p-4 md:p-8">
            <AdminImpersonationBanner />
            <DemoModeBanner />
            <Outlet />
          </main>
        </div>
      </div>
    </TourProvider>
  );
}

function TeamMemberLayout() {
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);
  return (
    <div className="app-bg flex min-h-screen">
      <TeamMemberViewLogger />
      <TeamMemberSidebar isMobileOpen={isMobileNavOpen} onCloseMobile={() => setIsMobileNavOpen(false)} />
      <div className="flex min-h-screen min-w-0 flex-1 flex-col lg:pl-64">
        <MobileTopBar onOpen={() => setIsMobileNavOpen(true)} />
        <TeamMemberNavbar />
        <main className="min-w-0 flex-1 p-4 md:p-8">
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
      <div className="flex min-h-screen min-w-0 flex-1 flex-col lg:pl-64">
        <MobileTopBar onOpen={() => setIsMobileNavOpen(true)} />
        <AdminNavbar />
        <main className="min-w-0 flex-1 p-4 md:p-8">
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

function AffiliateLayout() {
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false);
  return (
    <div className="app-bg flex min-h-screen">
      <AffiliateSidebar isMobileOpen={isMobileNavOpen} onCloseMobile={() => setIsMobileNavOpen(false)} />
      <div className="flex min-h-screen min-w-0 flex-1 flex-col lg:pl-64">
        <MobileTopBar onOpen={() => setIsMobileNavOpen(true)} />
        <AffiliateNavbar />
        <main className="min-w-0 flex-1 p-4 md:p-8">
          <Outlet />
        </main>
      </div>
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
          <Route path={PUBLIC_ROUTES.becomeAffiliate} element={withSuspense(AffiliateSignup)} />
        </Route>

        {/* Auth — pages wrap themselves in <AuthLayout>, so no shared layout route here */}
        <Route path={AUTH_ROUTES.login} element={withSuspense(Login)} />
        <Route path={AUTH_ROUTES.register} element={withSuspense(LandlordRegistration)} />
        <Route path={AUTH_ROUTES.verifyEmail} element={withSuspense(VerifyEmail)} />
        <Route path={AUTH_ROUTES.forgotPassword} element={withSuspense(ForgotPassword)} />
        <Route path={AUTH_ROUTES.resetPassword} element={withSuspense(ResetPassword)} />
        <Route path={AUTH_ROUTES.teamActivate} element={withSuspense(TeamActivation)} />
        <Route path={AUTH_ROUTES.tenantLogin} element={withSuspense(TenantOtpLogin)} />

        {/* Forced password change — any authenticated user on a temporary password.
            ProtectedRoutes (no role filter) only checks that they're logged in. */}
        <Route element={<ProtectedRoutes />}>
          <Route path={AUTH_ROUTES.changePassword} element={withSuspense(ChangePassword)} />
        </Route>

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
            <Route path="messages" element={withSuspense(TenantMessagesInbox)} />
            <Route path="notifications" element={withSuspense(NotificationsPage)} />
            <Route path="notifications/send" element={withSuspense(SendNotificationLandlord)} />
            <Route path="tutorials" element={withSuspense(TutorialsPage)} />

            <Route path="settings" element={withSuspense(SettingsLayout)}>
              <Route index element={<Navigate to="general" replace />} />
              <Route path="general" element={withSuspense(GeneralSettings)} />
              <Route path="backup" element={withDemoBlock(BackupSettings)} />
              <Route path="alerts" element={withSuspense(AlertSettings)} />
              <Route path="account" element={withDemoBlock(AccountSettings)} />
              <Route path="documents" element={withSuspense(DocumentTemplates)} />
              <Route path="team" element={withDemoBlock(TeamManagement)} />
              <Route path="billing" element={withDemoBlock(BillingSettings)} />
              <Route path="sms-provider" element={withDemoBlock(SmsProviderSettings)} />
              <Route path="mpesa" element={withDemoBlock(MpesaStatus)} />
              <Route path="copilot" element={withDemoBlock(CopilotSettings)} />
              <Route path="audit" element={withSuspense(AuditTrail)} />
              <Route path="impersonation-requests" element={withDemoBlock(ImpersonationRequests)} />
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
            <Route element={<ProtectedRoutes requiredPermission={{ module: "expenses", level: "view" }} />}>
              <Route path="expenses" element={withSuspense(ExpensesPage)} />
            </Route>
            <Route element={<ProtectedRoutes requiredPermission={{ module: "utilities", level: "view" }} />}>
              <Route path="utilities" element={withSuspense(UtilitiesPage)} />
            </Route>
            <Route element={<ProtectedRoutes requiredPermission={{ module: "maintenance", level: "view" }} />}>
              <Route path="maintenance" element={withSuspense(MaintenancePage)} />
            </Route>
            <Route element={<ProtectedRoutes requiredPermission={{ module: "groups", level: "view" }} />}>
              <Route path="groups" element={withSuspense(PropertyGroupsPage)} />
            </Route>
            <Route element={<ProtectedRoutes requiredPermission={{ module: "reports", level: "view" }} />}>
              <Route path="reports/statements" element={withSuspense(StatementsPage)} />
              <Route path="reports/insights" element={withSuspense(InsightsPage)} />
            </Route>
            <Route element={<ProtectedRoutes requiredPermission={{ module: "messages", level: "view" }} />}>
              <Route path="communications" element={withSuspense(CommunicationsPage)} />
              <Route path="messages" element={withSuspense(TenantMessagesInbox)} />
            </Route>
            <Route path="notifications" element={withSuspense(NotificationsPage)} />
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
            <Route path="messages" element={withSuspense(TenantMessages)} />
            <Route path="profile" element={withSuspense(TenantProfile)} />
            <Route path="notifications" element={withSuspense(NotificationsPage)} />
          </Route>
        </Route>

        {/* Affiliate portal */}
        <Route element={<ProtectedRoutes allowedRoles={[USER_ROLES.AFFILIATE]} />}>
          <Route path={AFFILIATE_ROUTES.root} element={<AffiliateLayout />}>
            <Route index element={<Navigate to="dashboard" replace />} />
            <Route path="dashboard" element={withSuspense(AffiliateDashboard)} />
            <Route path="referrals" element={withSuspense(AffiliateReferrals)} />
            <Route path="earnings" element={withSuspense(AffiliateEarnings)} />
            <Route path="withdrawals" element={withSuspense(AffiliateWithdrawals)} />
            <Route path="profile" element={withSuspense(AffiliateProfile)} />
            <Route path="notifications" element={withSuspense(NotificationsPage)} />
          </Route>
        </Route>

        {/* System Admin portal */}
        <Route element={<ProtectedRoutes allowedRoles={[USER_ROLES.SYSTEM_ADMIN]} />}>
          <Route path={ADMIN_ROUTES.root} element={<AdminLayout />}>
            <Route index element={<Navigate to="dashboard" replace />} />
            <Route path="dashboard" element={withSuspense(AdminDashboard)} />
            <Route path="landlords" element={withSuspense(LandlordsManagement)} />
            <Route path="landlords/:id" element={withSuspense(LandlordDetail)} />
            <Route path="units" element={withSuspense(AdminUnits)} />
            <Route path="units/:id" element={withSuspense(UnitDetail)} />
            <Route path="tenants" element={withSuspense(AdminTenants)} />
            <Route path="tenants/:id" element={withSuspense(TenantDetail)} />
            <Route path="team-members" element={withSuspense(AdminTeamMembers)} />
            <Route path="team-members/:id" element={withSuspense(TeamMemberDetail)} />
            <Route path="properties" element={withSuspense(AdminProperties)} />
            <Route path="properties/:id" element={withSuspense(PropertyDetail)} />
            <Route path="pricing" element={withSuspense(PricingPackages)} />
            <Route path="pricing/:id" element={withSuspense(PackageDetail)} />
            <Route path="sms" element={withSuspense(SmsManagement)} />
            <Route path="billing" element={withSuspense(AdminBilling)} />
            <Route path="copilot" element={withSuspense(CopilotManagement)} />
            <Route path="trials" element={withSuspense(TrialConfig)} />
            <Route path="impersonation" element={withSuspense(Impersonation)} />
            <Route path="audit" element={withSuspense(MasterAuditLogs)} />
            <Route path="notifications" element={withSuspense(NotificationsPage)} />
            <Route path="notifications/send" element={withSuspense(SendNotificationAdmin)} />
            <Route path="affiliates" element={withSuspense(AffiliatesManagement)} />
            <Route path="affiliates/withdrawals" element={withSuspense(AffiliateWithdrawalsQueue)} />
            <Route path="affiliates/reports" element={withSuspense(AffiliateReports)} />
            <Route path="affiliates/settings" element={withSuspense(AffiliateProgramSettings)} />
            <Route path="affiliates/:id" element={withSuspense(AdminAffiliateDetail)} />
          </Route>
        </Route>

        <Route path={NOT_FOUND_ROUTE} element={<NotFound />} />
      </Routes>
    </ErrorBoundary>
  );
}
