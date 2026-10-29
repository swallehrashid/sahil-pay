export const env = {
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || "http://localhost:5000/api",
  cloudinaryCloudName: import.meta.env.VITE_CLOUDINARY_CLOUD_NAME || "",
  cloudinaryUploadPreset: import.meta.env.VITE_CLOUDINARY_UPLOAD_PRESET || "",
  // Google OAuth Web client ID (same value the backend verifies against). Blank
  // hides the "Continue with Google" buttons, so the app runs fine without it.
  googleClientId: import.meta.env.VITE_GOOGLE_CLIENT_ID || "",
  isDev: import.meta.env.DEV,
  isProd: import.meta.env.PROD,
};

export default env;
