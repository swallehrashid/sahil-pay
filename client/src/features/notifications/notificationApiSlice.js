import { apiSlice } from "@/store/apiSlice";

// §8 — mirrors server/routes/notification_routes.py. Every endpoint here
// scopes to the caller's OWN notifications server-side (recipient_user_id
// from the JWT) — usable identically from any of the four portals.
export const notificationApiSlice = apiSlice.injectEndpoints({
  endpoints: (builder) => ({
    getNotifications: builder.query({
      query: (params) => ({ url: "/notifications/", params }),
      providesTags: ["Notification"],
    }),
    getUnreadCount: builder.query({
      query: () => "/notifications/unread-count",
      providesTags: ["Notification"],
    }),
    markNotificationRead: builder.mutation({
      query: (id) => ({ url: `/notifications/${id}/read`, method: "POST" }),
      invalidatesTags: ["Notification"],
    }),
    markAllNotificationsRead: builder.mutation({
      query: () => ({ url: "/notifications/read-all", method: "POST" }),
      invalidatesTags: ["Notification"],
    }),
    getNotificationTemplates: builder.query({
      query: () => "/notifications/templates",
    }),
    sendNotification: builder.mutation({
      query: (body) => ({ url: "/notifications/send", method: "POST", body }),
      invalidatesTags: ["Notification"],
    }),
  }),
});

export const {
  useGetNotificationsQuery,
  useGetUnreadCountQuery,
  useMarkNotificationReadMutation,
  useMarkAllNotificationsReadMutation,
  useGetNotificationTemplatesQuery,
  useSendNotificationMutation,
} = notificationApiSlice;
