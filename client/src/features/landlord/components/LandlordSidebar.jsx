import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  LayoutDashboard,
  Receipt,
  Wallet,
  ReceiptText,
  Users,
  Building2,
  DoorOpen,
  Gauge,
  Wrench,
  FolderTree,
  BarChart3,
  MessageSquare,
  MessagesSquare,
  Bell,
  GraduationCap,
  Settings as SettingsIcon,
  LogOut,
  FlaskConical,
  Landmark,
  FileSpreadsheet,
  AlertCircle,
  AlertTriangle,
  FileText,
  Coins,
  UploadCloud,
  BookOpen,
} from "lucide-react";
import Sidebar from "@/components/layout/Sidebar";
import { LANDLORD_ROUTES, AUTH_ROUTES } from "@/config/routePaths";
import { useAuth } from "@/hooks/useAuth";
import { ANCHORS } from "@/features/landlord/tutorials/anchors";
import { useGetEtimsScopeQuery } from "@/features/landlord/etims/etimsApiSlice";
import { useDemoMode } from "@/features/landlord/useDemoMode";
import DemoModeEnterDialog from "@/features/landlord/components/DemoModeEnterDialog";

const NAV_ITEMS = [
  { to: LANDLORD_ROUTES.dashboard, label: "Dashboard", icon: <LayoutDashboard className="h-4 w-4" />, end: true, dataTour: ANCHORS.sidebar.dashboard },
  { to: LANDLORD_ROUTES.invoices, label: "Invoices", icon: <Receipt className="h-4 w-4" />, dataTour: ANCHORS.sidebar.invoices },
  { to: LANDLORD_ROUTES.payments, label: "Payments", icon: <Wallet className="h-4 w-4" />, dataTour: ANCHORS.sidebar.payments },
  // Money that arrived but couldn't be attributed with certainty. Sits next to
  // Payments because that is where someone looks when a tenant says they paid.
  { to: LANDLORD_ROUTES.reviewQueue, label: "Review queue", icon: <AlertCircle className="h-4 w-4" /> },
  // Property managers remit collections to each owner; landlords running their
  // own blocks simply never use it. One entry, two tabs inside (runs → ledger):
  // as two sibling links called "Owner payouts" and "Payout runs" they read as
  // duplicates, and neither name told you which one you wanted.
  { to: LANDLORD_ROUTES.payouts, label: "Owner payouts", icon: <Coins className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.expenses, label: "Expenses", icon: <ReceiptText className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.tenants, label: "Tenants", icon: <Users className="h-4 w-4" />, dataTour: ANCHORS.sidebar.tenants },
  { to: LANDLORD_ROUTES.properties, label: "Properties", icon: <Building2 className="h-4 w-4" />, dataTour: ANCHORS.sidebar.properties },
  { to: LANDLORD_ROUTES.units, label: "Units", icon: <DoorOpen className="h-4 w-4" />, dataTour: ANCHORS.sidebar.units },
  { to: LANDLORD_ROUTES.utilities, label: "Utilities", icon: <Gauge className="h-4 w-4" />, dataTour: ANCHORS.sidebar.utilities },
  // Sits with Properties/Units/Tenants because that is what it creates, and
  // because "where do I upload my spreadsheet?" is asked while looking at an
  // empty tenants list.
  { to: LANDLORD_ROUTES.imports, label: "Bulk import", icon: <UploadCloud className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.maintenance, label: "Maintenance", icon: <Wrench className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.groups, label: "Property Groups", icon: <FolderTree className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.leases, label: "Leases", icon: <FileText className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.reportsStatements, label: "Reports", icon: <BarChart3 className="h-4 w-4" />, dataTour: ANCHORS.sidebar.reports },
  // Its own entry rather than a tab inside Reports: a penalty is not rent, is
  // not commissionable, and gets reconciled separately from both.
  { to: LANDLORD_ROUTES.reportsPenalties, label: "Penalties", icon: <AlertTriangle className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.communications, label: "Communications", icon: <MessageSquare className="h-4 w-4" />, dataTour: ANCHORS.sidebar.communications },
  { to: LANDLORD_ROUTES.messages, label: "Tenant Messages", icon: <MessagesSquare className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.notifications, label: "Notifications", icon: <Bell className="h-4 w-4" />, dataTour: ANCHORS.sidebar.notifications },
  { to: LANDLORD_ROUTES.tutorials, label: "Help & Tutorials", icon: <GraduationCap className="h-4 w-4" />, dataTour: ANCHORS.sidebar.tutorials },
  // The admin-authored article library — distinct from the first-run product
  // tour above, which is hardcoded in the client.
  { to: LANDLORD_ROUTES.help, label: "Guides", icon: <BookOpen className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.settings.root, label: "Settings", icon: <SettingsIcon className="h-4 w-4" />, dataTour: ANCHORS.sidebar.settings },
];

// Shown ONLY when at least one in-scope property has eTIMS switched on
// (SAHILPAY_ETIMS_KRA_COMPLIANCE_SPEC.md §4.2). Not greyed out, not shown with
// a "set this up" hint — an account that hasn't opted in simply doesn't have
// these links.
const ETIMS_NAV_ITEMS = [
  { to: LANDLORD_ROUTES.etimsRegister, label: "eTIMS Register", icon: <Landmark className="h-4 w-4" /> },
  { to: LANDLORD_ROUTES.kraMonthly, label: "KRA Monthly Report", icon: <FileSpreadsheet className="h-4 w-4" /> },
];

export default function LandlordSidebar({ isMobileOpen, onCloseMobile }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { isActive: isDemoActive, enter, exit, isEntering, isExiting } = useDemoMode();
  const [showEnterConfirm, setShowEnterConfirm] = useState(false);
  const { data: etimsScope } = useGetEtimsScopeQuery();

  // Insert the two eTIMS links just above Settings, so they sit with the other
  // reporting tools rather than at the bottom of the list.
  const items = etimsScope?.enabled
    ? [...NAV_ITEMS.slice(0, -1), ...ETIMS_NAV_ITEMS, NAV_ITEMS[NAV_ITEMS.length - 1]]
    : NAV_ITEMS;

  const handleLogout = () => {
    logout();
    navigate(AUTH_ROUTES.login);
  };

  return (
    <>
      <Sidebar
        items={items}
        isMobileOpen={isMobileOpen}
        onCloseMobile={onCloseMobile}
        footer={
          <div className="space-y-2 px-1">
            <p className="truncate text-xs text-white/40">{user?.email}</p>
            <button
              onClick={() => (isDemoActive ? exit() : setShowEnterConfirm(true))}
              disabled={isEntering || isExiting}
              className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-white/60 transition-colors hover:bg-white/5 hover:text-white"
            >
              <FlaskConical className="h-4 w-4" /> {isDemoActive ? "Exit demo mode" : "Try demo mode"}
            </button>
            <button
              onClick={handleLogout}
              className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-sm text-white/60 transition-colors hover:bg-white/5 hover:text-white"
            >
              <LogOut className="h-4 w-4" /> Log out
            </button>
          </div>
        }
      />
      <DemoModeEnterDialog
        isOpen={showEnterConfirm}
        onClose={() => setShowEnterConfirm(false)}
        onConfirm={async () => {
          await enter();
          setShowEnterConfirm(false);
        }}
        isLoading={isEntering}
      />
    </>
  );
}
