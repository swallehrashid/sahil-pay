import { configureStore } from "@reduxjs/toolkit";
import { setupListeners } from "@reduxjs/toolkit/query";
import { apiSlice } from "./apiSlice";
import rootReducers from "./rootReducer";

export const store = configureStore({
  reducer: {
    ...rootReducers,
    [apiSlice.reducerPath]: apiSlice.reducer,
  },
  middleware: (getDefaultMiddleware) => getDefaultMiddleware().concat(apiSlice.middleware),
  devTools: import.meta.env.DEV,
});

// Lets a query opt into refetchOnFocus / refetchOnReconnect.
setupListeners(store.dispatch);

export default store;
