import { apiSlice } from "@/store/apiSlice";

// §4.18 — mirrors server/routes/document_routes.py.
export const documentApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getDocumentTemplates: builder.query({
      query: () => "/documents/templates",
      providesTags: ["DocumentTemplate"],
    }),
    createDocumentTemplate: builder.mutation({
      query: (body) => ({ url: "/documents/templates", method: "POST", body }),
      invalidatesTags: ["DocumentTemplate"],
    }),
    updateDocumentTemplate: builder.mutation({
      query: ({ id, ...body }) => ({ url: `/documents/templates/${id}`, method: "PUT", body }),
      invalidatesTags: ["DocumentTemplate"],
    }),
    deleteDocumentTemplate: builder.mutation({
      query: (id) => ({ url: `/documents/templates/${id}`, method: "DELETE" }),
      invalidatesTags: ["DocumentTemplate"],
    }),
    sendDocument: builder.mutation({
      query: (body) => ({ url: "/documents/send", method: "POST", body }),
    }),
  }),
});

export const {
  useGetDocumentTemplatesQuery,
  useCreateDocumentTemplateMutation,
  useUpdateDocumentTemplateMutation,
  useDeleteDocumentTemplateMutation,
  useSendDocumentMutation,
} = documentApiSlice;
