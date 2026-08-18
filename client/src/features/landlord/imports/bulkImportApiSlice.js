import { apiSlice } from "@/store/apiSlice";

// Mirrors server/routes/bulk_import_routes.py.
//
// `inspect` posts the file as multipart and gets back the headers, every parsed
// row and a suggested mapping. Every later call sends those ROWS back rather
// than re-uploading the file, so the table the preview showed and the table we
// write are provably the same one.
const unwrap = (response) => response?.data ?? response;

export const bulkImportApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getImportCatalogue: builder.query({
      query: () => "/imports/catalogue",
      transformResponse: unwrap,
    }),
    inspectImportFile: builder.mutation({
      query: ({ entity, file, sheet }) => {
        const body = new FormData();
        body.append("entity", entity);
        body.append("file", file);
        if (sheet) body.append("sheet", sheet);
        return { url: "/imports/inspect", method: "POST", body };
      },
      transformResponse: unwrap,
    }),
    validateImport: builder.mutation({
      query: ({ entity, ...body }) => ({
        url: `/imports/${entity}/validate`,
        method: "POST",
        body,
      }),
      transformResponse: unwrap,
    }),
    commitImport: builder.mutation({
      query: ({ entity, ...body }) => ({
        url: `/imports/${entity}/commit`,
        method: "POST",
        body,
      }),
      transformResponse: unwrap,
      // An import creates properties, units and tenants wholesale — anything
      // showing those is stale the moment it finishes.
      invalidatesTags: ["Property", "Unit", "Tenant", "Invoice"],
    }),

    getImportMappings: builder.query({
      query: (entity) => ({ url: "/imports/mappings", params: { entity } }),
      transformResponse: unwrap,
      providesTags: ["ImportMapping"],
    }),
    saveImportMapping: builder.mutation({
      query: (body) => ({ url: "/imports/mappings", method: "POST", body }),
      transformResponse: unwrap,
      invalidatesTags: ["ImportMapping"],
    }),
    deleteImportMapping: builder.mutation({
      query: (id) => ({ url: `/imports/mappings/${id}`, method: "DELETE" }),
      invalidatesTags: ["ImportMapping"],
    }),
  }),
});

export const {
  useGetImportCatalogueQuery,
  useInspectImportFileMutation,
  useValidateImportMutation,
  useCommitImportMutation,
  useGetImportMappingsQuery,
  useSaveImportMappingMutation,
  useDeleteImportMappingMutation,
} = bulkImportApiSlice;
