import { configureStore } from "@reduxjs/toolkit";
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

export default store;
