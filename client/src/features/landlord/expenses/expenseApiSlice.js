import { apiSlice } from "@/store/apiSlice";

// §4.4 — mirrors server/routes/expense_routes.py. Statuses exactly: confirmed/pending.
export const expenseApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getExpenses: builder.query({
      query: (params) => ({ url: "/expenses", params }),
      providesTags: ["Expense"],
    }),
    getExpense: builder.query({
      query: (id) => `/expenses/${id}`,
      providesTags: (result, error, id) => [{ type: "Expense", id }],
    }),
    createExpense: builder.mutation({
      query: (body) => ({ url: "/expenses", method: "POST", body }),
      invalidatesTags: ["Expense"],
    }),
    updateExpense: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/expenses/${id}`, method: "PUT", body }),
      invalidatesTags: (result, error, { id }) => [{ type: "Expense", id }, "Expense"],
    }),
    deleteExpense: builder.mutation({
      query: (id) => ({ url: `/expenses/${id}`, method: "DELETE" }),
      invalidatesTags: ["Expense"],
    }),
    getRecurringExpenses: builder.query({
      query: () => "/expenses/recurring",
      providesTags: ["RecurringExpense"],
    }),
    createRecurringExpense: builder.mutation({
      query: (body) => ({ url: "/expenses/recurring", method: "POST", body }),
      invalidatesTags: ["RecurringExpense"],
    }),
    updateRecurringExpense: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/expenses/recurring/${id}`, method: "PUT", body }),
      invalidatesTags: ["RecurringExpense"],
    }),
    deleteRecurringExpense: builder.mutation({
      query: (id) => ({ url: `/expenses/recurring/${id}`, method: "DELETE" }),
      invalidatesTags: ["RecurringExpense"],
    }),
  }),
});

export const {
  useGetExpensesQuery,
  useGetExpenseQuery,
  useCreateExpenseMutation,
  useUpdateExpenseMutation,
  useDeleteExpenseMutation,
  useGetRecurringExpensesQuery,
  useCreateRecurringExpenseMutation,
  useUpdateRecurringExpenseMutation,
  useDeleteRecurringExpenseMutation,
} = expenseApiSlice;
