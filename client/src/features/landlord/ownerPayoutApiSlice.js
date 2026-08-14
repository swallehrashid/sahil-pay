import { apiSlice } from "@/store/apiSlice";

// Owner payouts — money a property manager has remitted to each property's
// owner. Mirrors server/routes/owner_payout_routes.py.
//
// A payout is not an expense: it is the owner's own money being handed over, so
// it never enters expense totals or the commission base. The property statement
// shows it as "Remitted to owner" and closes with what the manager retained.
export const ownerPayoutApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getOwnerPayouts: builder.query({
      query: (params) => ({ url: "/owner-payouts/", params }),
      providesTags: ["OwnerPayout"],
    }),
    createOwnerPayout: builder.mutation({
      query: (body) => ({ url: "/owner-payouts/", method: "POST", body }),
      // The property statement's "remitted" line changes with it.
      invalidatesTags: ["OwnerPayout", "Report"],
    }),
    updateOwnerPayout: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/owner-payouts/${id}`, method: "PUT", body }),
      invalidatesTags: ["OwnerPayout", "Report"],
    }),
    deleteOwnerPayout: builder.mutation({
      query: (id) => ({ url: `/owner-payouts/${id}`, method: "DELETE" }),
      invalidatesTags: ["OwnerPayout", "Report"],
    }),
  }),
});

export const {
  useGetOwnerPayoutsQuery,
  useCreateOwnerPayoutMutation,
  useUpdateOwnerPayoutMutation,
  useDeleteOwnerPayoutMutation,
} = ownerPayoutApiSlice;
