import { apiSlice } from "@/store/apiSlice";

// §4.9 — mirrors server/routes/maintenance_routes.py. Statuses exactly: open/in_progress/closed.
export const maintenanceApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getMaintenanceRequests: builder.query({
      query: (params) => ({ url: "/maintenance", params }),
      providesTags: ["Maintenance"],
    }),
    getMaintenanceRequest: builder.query({
      query: (id) => `/maintenance/${id}`,
      providesTags: (result, error, id) => [{ type: "Maintenance", id }],
    }),
    createMaintenanceRequest: builder.mutation({
      query: (body) => ({ url: "/maintenance", method: "POST", body }),
      invalidatesTags: ["Maintenance"],
    }),
    updateMaintenanceRequest: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/maintenance/${id}`, method: "PUT", body }),
      invalidatesTags: (result, error, { id }) => [{ type: "Maintenance", id }, "Maintenance"],
    }),
    deleteMaintenanceRequest: builder.mutation({
      query: (id) => ({ url: `/maintenance/${id}`, method: "DELETE" }),
      invalidatesTags: ["Maintenance"],
    }),
    createExpenseFromMaintenance: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/maintenance/${id}/create-expense`, method: "POST", body }),
      invalidatesTags: ["Maintenance", "Expense"],
    }),
  }),
});

export const {
  useGetMaintenanceRequestsQuery,
  useGetMaintenanceRequestQuery,
  useCreateMaintenanceRequestMutation,
  useUpdateMaintenanceRequestMutation,
  useDeleteMaintenanceRequestMutation,
  useCreateExpenseFromMaintenanceMutation,
} = maintenanceApiSlice;
