import axios, { AxiosInstance, AxiosError } from "axios";

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || "https://columbia-4-0.onrender.com";

export const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 90000,
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
    if (
      error.response?.status === 503 ||
      (error.response?.data as any)?.status === "scrapers_running" ||
      (error.response?.data as any)?.pipeline_running === true
    ) {
      window.dispatchEvent(
        new CustomEvent("vantis-scraping-active", {
          detail: {
            pipeline_running: true,
            message:
              (error.response?.data as any)?.message ||
              (error.response?.data as any)?.detail ||
              "Hey, we are currently scraping! To save RAM, we can't let you access anything right now. This might take up to one hour.",
          },
        })
      );
    }

    const message =
      (error.response?.data as any)?.detail ||
      (error.response?.data as any)?.message ||
      (error.response?.data as any)?.error ||
      error.message ||
      "An unexpected network error occurred";
    return Promise.reject(new Error(message));
  }
);

export default apiClient;
