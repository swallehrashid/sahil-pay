#!/usr/bin/env bash
# =============================================================================
# SahilPay — Front-end scaffold generator
# Run this from the ROOT of your `client/` folder (where package.json lives).
#   cd client
#   bash create-structure.sh
# It only creates folders + empty files; it never overwrites existing ones.
# =============================================================================
set -e
cd "$(dirname "$0")"

# ---- helper: make an empty file only if it doesn't exist --------------------
nf() { mkdir -p "$(dirname "$1")"; [ -e "$1" ] || : > "$1"; }

echo "Scaffolding SahilPay front-end..."

# ---- top-level config -------------------------------------------------------
nf src/config/env.js
nf src/config/routePaths.js

# ---- assets -----------------------------------------------------------------
mkdir -p src/assets/images src/assets/logos src/assets/illustrations

# ---- global components ------------------------------------------------------
nf src/components/Footer.jsx
nf src/components/Navbar.jsx
nf src/components/ProtectedRoutes.jsx

for f in Button Input Select Checkbox Textarea DatePicker FileUpload Modal Drawer \
         ConfirmDialog Dropdown Tabs Badge StatusBadge Pagination Spinner Skeleton \
         EmptyState Toast SummaryCard ExportButtons; do
  nf "src/components/ui/$f.jsx"
done

for f in ResponsiveTable TableToolbar FilterPanel; do nf "src/components/tables/$f.jsx"; done
for f in DashboardLayout Sidebar PageHeader AuthLayout PublicLayout; do nf "src/components/layout/$f.jsx"; done
for f in PerformanceChart OccupancyChart ComparativeChart; do nf "src/components/charts/$f.jsx"; done
for f in ErrorBoundary NotFound; do nf "src/components/feedback/$f.jsx"; done

# ---- context ----------------------------------------------------------------
nf src/context/AuthContext.jsx

# ---- store ------------------------------------------------------------------
nf src/store/apiSlice.js
nf src/store/store.js
nf src/store/rootReducer.js

# ---- utils ------------------------------------------------------------------
for f in currencyFormatter dateFormatter constants permissions validators \
         downloadFile tokenStorage tableAdapters; do
  nf "src/utils/$f.js"
done

# ---- hooks ------------------------------------------------------------------
for f in useAuth usePermissions useDebounce useMediaQuery; do nf "src/hooks/$f.js"; done

# ---- routes -----------------------------------------------------------------
nf src/routes/AppRoutes.jsx
nf src/routes/roleRedirect.js

# ---- features: auth ---------------------------------------------------------
nf src/features/auth/components/AuthNavbar.jsx
nf src/features/auth/components/OtpInput.jsx
nf src/features/auth/authApiSlice.js
nf src/features/auth/otpApiSlice.js
nf src/features/auth/authSlice.js
for f in Login LandlordRegistration VerifyEmail ForgotPassword ResetPassword \
         TeamActivation TenantOtpLogin; do
  nf "src/features/auth/$f.jsx"
done

# ---- features: public -------------------------------------------------------
nf src/features/public/components/PublicNavbar.jsx
for f in Home About Features Pricing Contact FAQ PrivacyPolicy TermsOfService; do
  nf "src/features/public/$f.jsx"
done

# ---- features: landlord -----------------------------------------------------
for f in LandlordNavbar LandlordSidebar QuickActions SubscriptionShortcut ImpersonationBanner; do
  nf "src/features/landlord/components/$f.jsx"
done
nf src/features/landlord/landlordApiSlice.js
nf src/features/landlord/LandlordDashboard.jsx

# properties
nf src/features/landlord/properties/propertyApiSlice.js
nf src/features/landlord/properties/PropertiesPage.jsx
nf src/features/landlord/properties/PropertyForm.jsx
# units
nf src/features/landlord/units/unitApiSlice.js
nf src/features/landlord/units/UnitsPage.jsx
nf src/features/landlord/units/UnitForm.jsx
# tenants
nf src/features/landlord/tenants/tenantApiSlice.js
nf src/features/landlord/tenants/TenantsPage.jsx
nf src/features/landlord/tenants/TenantForm.jsx
nf src/features/landlord/tenants/TenantTransactions.jsx
nf src/features/landlord/tenants/DeletedTenants.jsx
nf src/features/landlord/tenants/ShiftTenantModal.jsx
# invoices
nf src/features/landlord/invoices/invoiceApiSlice.js
nf src/features/landlord/invoices/InvoicesPage.jsx
nf src/features/landlord/invoices/InvoiceForm.jsx
nf src/features/landlord/invoices/BulkInvoices.jsx
nf src/features/landlord/invoices/GenerateRentInvoices.jsx
nf src/features/landlord/invoices/GenerateRecurringInvoices.jsx
nf src/features/landlord/invoices/GeneratePenaltyInvoices.jsx
nf src/features/landlord/invoices/GenerateCustomInvoices.jsx
# payments
nf src/features/landlord/payments/paymentApiSlice.js
nf src/features/landlord/payments/PaymentsPage.jsx
nf src/features/landlord/payments/RecordPaymentForm.jsx
nf src/features/landlord/payments/BankStatementUpload.jsx
nf src/features/landlord/payments/BankStatementReview.jsx
nf src/features/landlord/payments/ReassignTenantModal.jsx
# expenses
nf src/features/landlord/expenses/expenseApiSlice.js
nf src/features/landlord/expenses/ExpensesPage.jsx
nf src/features/landlord/expenses/ExpenseForm.jsx
nf src/features/landlord/expenses/RecurringExpenses.jsx
# utilities
nf src/features/landlord/utilities/utilityApiSlice.js
nf src/features/landlord/utilities/UtilitiesPage.jsx
nf src/features/landlord/utilities/RecordUtilityForm.jsx
nf src/features/landlord/utilities/BulkUploadUtilities.jsx
# maintenance
nf src/features/landlord/maintenance/maintenanceApiSlice.js
nf src/features/landlord/maintenance/MaintenancePage.jsx
nf src/features/landlord/maintenance/MaintenanceForm.jsx
nf src/features/landlord/maintenance/CreateExpenseFromMaintenance.jsx
# groups
nf src/features/landlord/groups/groupApiSlice.js
nf src/features/landlord/groups/PropertyGroupsPage.jsx
nf src/features/landlord/groups/GroupForm.jsx
nf src/features/landlord/groups/AssignManagerModal.jsx
# reports
nf src/features/landlord/reports/reportApiSlice.js
nf src/features/landlord/reports/StatementsPage.jsx
nf src/features/landlord/reports/TenantStatement.jsx
nf src/features/landlord/reports/PropertyStatement.jsx
nf src/features/landlord/reports/ArrearsReport.jsx
nf src/features/landlord/reports/ExpensesReport.jsx
nf src/features/landlord/reports/ComparativeReport.jsx
nf src/features/landlord/reports/GroupingReport.jsx
nf src/features/landlord/reports/InsightsPage.jsx
nf src/features/landlord/reports/OccupancyInsights.jsx
# communications
nf src/features/landlord/communications/communicationApiSlice.js
nf src/features/landlord/communications/CommunicationsPage.jsx
nf src/features/landlord/communications/MessageTemplates.jsx
# settings
nf src/features/landlord/settings/settingsApiSlice.js
nf src/features/landlord/settings/teamApiSlice.js
nf src/features/landlord/settings/billingApiSlice.js
nf src/features/landlord/settings/documentApiSlice.js
nf src/features/landlord/settings/mpesaApiSlice.js
nf src/features/landlord/settings/auditApiSlice.js
nf src/features/landlord/settings/SettingsLayout.jsx
nf src/features/landlord/settings/GeneralSettings.jsx
nf src/features/landlord/settings/BackupSettings.jsx
nf src/features/landlord/settings/AlertSettings.jsx
nf src/features/landlord/settings/AccountSettings.jsx
nf src/features/landlord/settings/DocumentTemplates.jsx
nf src/features/landlord/settings/TeamManagement.jsx
nf src/features/landlord/settings/TeamMemberForm.jsx
nf src/features/landlord/settings/PermissionMatrix.jsx
nf src/features/landlord/settings/BillingSettings.jsx
nf src/features/landlord/settings/MpesaStatus.jsx
nf src/features/landlord/settings/AuditTrail.jsx
nf src/features/landlord/settings/ImpersonationRequests.jsx

# ---- features: teamMember ---------------------------------------------------
nf src/features/teamMember/components/TeamMemberNavbar.jsx
nf src/features/teamMember/components/TeamMemberSidebar.jsx
nf src/features/teamMember/teamMemberApiSlice.js
nf src/features/teamMember/TeamMemberDashboard.jsx
nf src/features/teamMember/TeamMemberProfile.jsx

# ---- features: tenant -------------------------------------------------------
nf src/features/tenant/components/TenantNavbar.jsx
nf src/features/tenant/tenantPortalApiSlice.js
nf src/features/tenant/TenantDashboard.jsx
nf src/features/tenant/TenantPayments.jsx
nf src/features/tenant/TenantStatement.jsx
nf src/features/tenant/TenantProfile.jsx
nf src/features/tenant/TenantMaintenance.jsx

# ---- features: admin --------------------------------------------------------
nf src/features/admin/components/AdminNavbar.jsx
nf src/features/admin/components/AdminSidebar.jsx
nf src/features/admin/adminApiSlice.js
nf src/features/admin/adminPricingApiSlice.js
nf src/features/admin/adminTrialApiSlice.js
nf src/features/admin/adminImpersonationApiSlice.js
nf src/features/admin/AdminDashboard.jsx
nf src/features/admin/LandlordsManagement.jsx
nf src/features/admin/LandlordDetail.jsx
nf src/features/admin/PricingPackages.jsx
nf src/features/admin/TrialConfig.jsx
nf src/features/admin/Impersonation.jsx
nf src/features/admin/MasterAuditLogs.jsx

echo "Done. SahilPay front-end structure created."
