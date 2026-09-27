import { apiSlice } from "@/store/apiSlice";

// §4.14–§4.17 — mirrors server/routes/settings_routes.py (general/automation/alerts/account/backup).
export const settingsApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getGeneralSettings: builder.query({
      query: () => "/settings/general",
      providesTags: ["Settings"],
    }),
    updateGeneralSettings: builder.mutation({
      query: (body) => ({ url: "/settings/general", method: "PUT", body }),
      invalidatesTags: ["Settings"],
    }),
    getAutomationSettings: builder.query({
      query: () => "/settings/automation",
      providesTags: ["Settings"],
    }),
    updateAutomationSettings: builder.mutation({
      query: (body) => ({ url: "/settings/automation", method: "PUT", body }),
      invalidatesTags: ["Settings"],
    }),
    getAlertSettings: builder.query({
      query: () => "/settings/alerts",
      providesTags: ["Settings"],
    }),
    updateAlertSettings: builder.mutation({
      query: (body) => ({ url: "/settings/alerts", method: "PUT", body }),
      invalidatesTags: ["Settings"],
    }),
    getAccountSettings: builder.query({
      query: () => "/settings/account",
      providesTags: ["Settings"],
    }),
    updateAccountSettings: builder.mutation({
      query: (body) => ({ url: "/settings/account", method: "PUT", body }),
      invalidatesTags: ["Settings", "Me"],
    }),
    generateAgentCode: builder.mutation({
      query: () => ({ url: "/settings/account/agent-code", method: "POST" }),
      invalidatesTags: ["Settings"],
    }),
    // Dedicated, verified change-password flow (current → new → confirm).
    changePassword: builder.mutation({
      query: (body) => ({ url: "/settings/account/change-password", method: "POST", body }),
    }),
    generateBackup: builder.mutation({
      query: (body) => ({ url: "/settings/backup", method: "POST", body }),
      invalidatesTags: ["Backup"],
    }),
    getBackups: builder.query({
      query: () => "/settings/backup",
      providesTags: ["Backup"],
    }),
    // Backup & Delete (owner only): what would go, then password → phrase → wipe.
    getWipeInfo: builder.query({
      query: () => "/settings/wipe",
      keepUnusedDataFor: 0,
    }),
    verifyWipePassword: builder.mutation({
      query: (body) => ({ url: "/settings/wipe/verify-password", method: "POST", body }),
    }),
    wipeAccount: builder.mutation({
      query: (body) => ({ url: "/settings/wipe", method: "POST", body }),
    }),
    // Synchronous, detailed backup preview (JSON) for a scope — the download
    // (Excel/PDF, with column selection) hits the same endpoint via ReportView.
    getBackupPreview: builder.query({
      query: (params) => ({ url: "/settings/backup/generate", params }),
    }),
    // Run the enabled scheduled automations now (verifies the toggles work).
    runAutomations: builder.mutation({
      query: () => ({ url: "/settings/automation/run", method: "POST" }),
      invalidatesTags: ["Communication", "Invoice", "Tenant"],
    }),
  }),
});

export const {
  useGetGeneralSettingsQuery,
  useUpdateGeneralSettingsMutation,
  useGetAutomationSettingsQuery,
  useUpdateAutomationSettingsMutation,
  useGetAlertSettingsQuery,
  useUpdateAlertSettingsMutation,
  useGetAccountSettingsQuery,
  useUpdateAccountSettingsMutation,
  useChangePasswordMutation,
  useGenerateAgentCodeMutation,
  useGenerateBackupMutation,
  useGetBackupsQuery,
  useGetBackupPreviewQuery,
  useGetWipeInfoQuery,
  useVerifyWipePasswordMutation,
  useWipeAccountMutation,
  useRunAutomationsMutation,
} = settingsApiSlice;
