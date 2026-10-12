import axios, { AxiosInstance, AxiosError } from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

export const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
});

// Request interceptor to attach JWT token
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem("vantis_token");
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor for consistent error handling and 401 handling
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ detail?: string; error?: string }>) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("vantis_token");
      localStorage.removeItem("vantis_user");
      // Redirect to login if not already on login page
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    const message =
      error.response?.data?.detail ||
      error.response?.data?.error ||
      error.message ||
      "An unexpected network error occurred";
    return Promise.reject(new Error(message));
  }
);

export default apiClient;
