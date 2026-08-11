import { apiSlice } from "@/store/apiSlice";

// Help Content CMS, admin side (server/routes/admin_tutorial_routes.py).
// Every endpoint is behind require_system_admin(), which also demands 2FA.
const unwrap = (response) => (response && "data" in response ? response.data : response);

export const adminTutorialApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    // --- Categories -------------------------------------------------------
    getAdminCategories: builder.query({
      query: () => "/admin/tutorial-categories",
      transformResponse: unwrap,
      providesTags: ["AdminTutorial"],
    }),
    createCategory: builder.mutation({
      query: (body) => ({ url: "/admin/tutorial-categories", method: "POST", body }),
      transformResponse: unwrap,
      invalidatesTags: ["AdminTutorial", "Tutorial"],
    }),
    updateCategory: builder.mutation({
      query: ({ id, ...body }) => ({
        url: `/admin/tutorial-categories/${id}`,
        method: "PATCH",
        body,
      }),
      transformResponse: unwrap,
      invalidatesTags: ["AdminTutorial", "Tutorial"],
    }),
    reorderCategories: builder.mutation({
      query: (order) => ({
        url: "/admin/tutorial-categories/reorder",
        method: "POST",
        body: { order },
      }),
      invalidatesTags: ["AdminTutorial", "Tutorial"],
    }),
    deleteCategory: builder.mutation({
      query: (id) => ({ url: `/admin/tutorial-categories/${id}`, method: "DELETE" }),
      invalidatesTags: ["AdminTutorial", "Tutorial"],
    }),

    // --- Articles ---------------------------------------------------------
    getAdminArticles: builder.query({
      query: (categoryId) => ({
        url: "/admin/tutorial-articles",
        params: categoryId ? { category_id: categoryId } : undefined,
      }),
      transformResponse: unwrap,
      providesTags: ["AdminTutorial"],
    }),
    getAdminArticle: builder.query({
      query: (id) => `/admin/tutorial-articles/${id}`,
      transformResponse: unwrap,
      providesTags: ["AdminTutorial"],
    }),
    createArticle: builder.mutation({
      query: (body) => ({ url: "/admin/tutorial-articles", method: "POST", body }),
      transformResponse: unwrap,
      invalidatesTags: ["AdminTutorial", "Tutorial"],
    }),
    updateArticle: builder.mutation({
      query: ({ id, ...body }) => ({
        url: `/admin/tutorial-articles/${id}`,
        method: "PATCH",
        body,
      }),
      transformResponse: unwrap,
      invalidatesTags: ["AdminTutorial", "Tutorial"],
    }),
    deleteArticle: builder.mutation({
      query: (id) => ({ url: `/admin/tutorial-articles/${id}`, method: "DELETE" }),
      invalidatesTags: ["AdminTutorial", "Tutorial"],
    }),
    // Live side-by-side preview. Uses the SAME renderer the reader side does,
    // so what the admin sees cannot drift from what a landlord gets.
    previewArticle: builder.mutation({
      query: (body_markdown) => ({
        url: "/admin/tutorial-articles/preview",
        method: "POST",
        body: { body_markdown },
      }),
      transformResponse: unwrap,
    }),

    // --- Images -----------------------------------------------------------
    getAdminImages: builder.query({
      query: (articleId) => ({
        url: "/admin/tutorial-images",
        params: { article_id: articleId ?? "null" },
      }),
      transformResponse: unwrap,
      providesTags: ["AdminTutorial"],
    }),
    // Multipart: RTK Query passes FormData through untouched.
    uploadImage: builder.mutation({
      query: (formData) => ({
        url: "/admin/tutorial-images",
        method: "POST",
        body: formData,
      }),
      transformResponse: unwrap,
      invalidatesTags: ["AdminTutorial"],
    }),
    // Replace keeps the same URL, so published articles update with no edit.
    replaceImage: builder.mutation({
      query: ({ id, formData }) => ({
        url: `/admin/tutorial-images/${id}/replace`,
        method: "POST",
        body: formData,
      }),
      transformResponse: unwrap,
      invalidatesTags: ["AdminTutorial"],
    }),
    updateImage: builder.mutation({
      query: ({ id, ...body }) => ({
        url: `/admin/tutorial-images/${id}`,
        method: "PATCH",
        body,
      }),
      transformResponse: unwrap,
      invalidatesTags: ["AdminTutorial"],
    }),
    deleteImage: builder.mutation({
      query: (id) => ({ url: `/admin/tutorial-images/${id}`, method: "DELETE" }),
      invalidatesTags: ["AdminTutorial"],
    }),
  }),
});

export const {
  useGetAdminCategoriesQuery,
  useCreateCategoryMutation,
  useUpdateCategoryMutation,
  useReorderCategoriesMutation,
  useDeleteCategoryMutation,
  useGetAdminArticlesQuery,
  useGetAdminArticleQuery,
  useCreateArticleMutation,
  useUpdateArticleMutation,
  useDeleteArticleMutation,
  usePreviewArticleMutation,
  useGetAdminImagesQuery,
  useUploadImageMutation,
  useReplaceImageMutation,
  useUpdateImageMutation,
  useDeleteImageMutation,
} = adminTutorialApiSlice;
