import { apiSlice } from "@/store/apiSlice";

// Complete, unpaginated option lists for form dropdowns (server/routes/lookup_routes.py).
// The page lists (/properties, /units, /tenants) return 20 rows at a time; a dropdown
// fed from one of those only ever offers the first 20. Use these hooks for any
// <Select> whose options are properties, units, tenants or team members.
export const lookupApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getPropertyOptions: builder.query({
      query: () => "/lookups/properties",
      providesTags: ["Property"],
    }),
    getUnitOptions: builder.query({
      query: (params) => ({ url: "/lookups/units", params }),
      providesTags: ["Unit", "Property"],
    }),
    getTenantOptions: builder.query({
      query: (params) => ({ url: "/lookups/tenants", params }),
      providesTags: ["Tenant", "Unit", "Property"],
    }),
    getTeamMemberOptions: builder.query({
      query: () => "/lookups/team-members",
      providesTags: ["TeamMember"],
    }),
  }),
});

export const {
  useGetPropertyOptionsQuery,
  useGetUnitOptionsQuery,
  useGetTenantOptionsQuery,
  useGetTeamMemberOptionsQuery,
} = lookupApiSlice;

// "Jane Wanjiru — B12, Riverside" so a tenant can be found by their unit or block
// as well as their name (two tenants often share a name at 1,000 tenants).
export function tenantOptionLabel(t) {
  const name = `${t.first_name ?? ""} ${t.last_name ?? ""}`.trim();
  const where = [t.unit_name, t.property_name].filter(Boolean).join(", ");
  return where ? `${name} — ${where}` : name;
}
