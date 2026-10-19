import apiClient from "./apiClient";
import { User } from "../types";

export interface LoginResponseData {
  access_token: string;
  token_type: string;
  user: User;
}

export const authService = {
  async login(username: string, password: string, rememberMe: boolean = false): Promise<User> {
    const response = await apiClient.post<LoginResponseData>("/api/auth/login", {
      username: username.trim(),
      password,
      remember_me: rememberMe,
    }, {
      timeout: 240000,
    });
    const { access_token, user } = response.data;
    localStorage.setItem("vantis_token", access_token);
    localStorage.setItem("vantis_user", JSON.stringify(user));
    return user;
  },

  async logout(): Promise<void> {
    try {
      await apiClient.post("/api/auth/logout");
    } catch {
      // Ignore network errors on logout
    } finally {
      localStorage.removeItem("vantis_token");
      localStorage.removeItem("vantis_user");
    }
  },

  async getCurrentUser(): Promise<User> {
    const response = await apiClient.get<User>("/api/auth/me");
    localStorage.setItem("vantis_user", JSON.stringify(response.data));
    return response.data;
  },

  async updateProfile(updates: Partial<User>): Promise<User> {
    const response = await apiClient.patch<User>("/api/profile", updates);
    localStorage.setItem("vantis_user", JSON.stringify(response.data));
    return response.data;
  },

  async resetPassword(newPassword: string, currentPassword?: string): Promise<{ status: string; message: string }> {
    const response = await apiClient.post<{ status: string; message: string }>("/api/auth/reset-password", {
      new_password: newPassword,
      current_password: currentPassword,
    });
    return response.data;
  },

  async uploadAvatar(file: File): Promise<{ status: string; avatar_url: string }> {
    const formData = new FormData();
    formData.append("file", file);
    const response = await apiClient.post<{ status: string; avatar_url: string }>("/api/auth/avatar", formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    });
    return response.data;
  },

  getSavedUser(): User | null {
    const str = localStorage.getItem("vantis_user");
    if (!str) return null;
    try {
      return JSON.parse(str) as User;
    } catch {
      return null;
    }
  },

  isAuthenticated(): boolean {
    return !!localStorage.getItem("vantis_token");
  },
};

export default authService;
