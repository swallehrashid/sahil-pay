import { apiSlice } from "@/store/apiSlice";

// Mirrors the /api/etims/import/* routes. Like the bulk importer, `inspect`
// uploads the file once and every later call sends the parsed ROWS back, so the
// table reviewed and the table written are provably the same one.
const unwrap = (response) => response?.data ?? response;

export const etimsImportApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getEtimsImportCatalogue: builder.query({
      query: () => "/etims/import/catalogue",
      transformResponse: unwrap,
    }),
    inspectEtimsFile: builder.mutation({
      query: ({ file, sheet }) => {
        const body = new FormData();
        body.append("file", file);
        if (sheet) body.append("sheet", sheet);
        return { url: "/etims/import/inspect", method: "POST", body };
      },
      transformResponse: unwrap,
    }),
    validateEtimsImport: builder.mutation({
      query: (body) => ({ url: "/etims/import/validate", method: "POST", body }),
      transformResponse: unwrap,
    }),
    commitEtimsImport: builder.mutation({
      query: (body) => ({ url: "/etims/import/commit", method: "POST", body }),
      transformResponse: unwrap,
      invalidatesTags: ["EtimsRegister", "Payment"],
    }),
  }),
});

export const {
  useGetEtimsImportCatalogueQuery,
  useInspectEtimsFileMutation,
  useValidateEtimsImportMutation,
  useCommitEtimsImportMutation,
} = etimsImportApiSlice;
