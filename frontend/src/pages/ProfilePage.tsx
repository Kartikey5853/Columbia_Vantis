import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  User as UserIcon,
  Mail,
  Shield,
  Clock,
  Bell,
  Sun,
  Moon,
  LogOut,
  Save,
  CheckCircle2,
  Camera,
} from "lucide-react";
import authService from "../services/authService";
import { User } from "../types";

export const ProfilePage: React.FC = () => {
  const navigate = useNavigate();
  const [user, setUser] = useState<User | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [avatarUrl, setAvatarUrl] = useState("");
  const [timezone, setTimezone] = useState("Asia/Kolkata");
  const [notifications, setNotifications] = useState(true);
  const [theme, setTheme] = useState("light");
  const [isLoading, setIsLoading] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  useEffect(() => {
    loadUser();
  }, []);

  const loadUser = async () => {
    try {
      const u = await authService.getCurrentUser();
      setUser(u);
      setDisplayName(u.display_name || "");
      setAvatarUrl(u.avatar_url || "");
      setTimezone(u.timezone || "Asia/Kolkata");
      setNotifications(u.notifications_enabled ?? true);
      setTheme(u.theme || "light");
    } catch {
      const saved = authService.getSavedUser();
      if (saved) {
        setUser(saved);
        setDisplayName(saved.display_name);
        setAvatarUrl(saved.avatar_url || "");
      }
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setSuccessMessage(null);
    try {
      const updated = await authService.updateProfile({
        display_name: displayName,
        avatar_url: avatarUrl,
        timezone,
        notifications_enabled: notifications,
        theme,
      });
      setUser(updated);
      setSuccessMessage("Profile preferences successfully updated.");
      setTimeout(() => setSuccessMessage(null), 3500);
    } catch (err: any) {
      alert("Error saving profile: " + err.message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleLogout = async () => {
    await authService.logout();
    navigate("/login");
  };

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-8 py-8 space-y-8">
      {/* Title */}
      <div>
        <h1 className="text-2xl sm:text-3xl font-black text-slate-900 tracking-tight">
          Account Profile &amp; Settings
        </h1>
        <p className="text-xs sm:text-sm text-slate-500 font-medium mt-0.5">
          Manage your Columbia intelligence account details and system preferences.
        </p>
      </div>

      {successMessage && (
        <div className="p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-700 text-xs font-bold flex items-center gap-2 animate-in fade-in">
          <CheckCircle2 className="w-4 h-4" />
          <span>{successMessage}</span>
        </div>
      )}

      {/* Main Profile Form */}
      <div className="bg-white rounded-3xl border border-slate-200/90 shadow-sm overflow-hidden">
        {/* Banner */}
        <div className="h-28 bg-gradient-to-r from-sky-400 via-[#079FE0] to-blue-600 relative px-6">
          <div className="absolute -bottom-8 left-8 flex items-end gap-4">
            <div className="relative w-20 h-20 rounded-2xl bg-white p-1 ring-4 ring-white shadow-md overflow-hidden">
              <img
                src={avatarUrl || user?.avatar_url || "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150&auto=format&fit=crop&q=80"}
                alt="Avatar"
                className="w-full h-full object-cover rounded-xl"
              />
            </div>
            <div className="mb-2">
              <h2 className="text-lg font-black text-slate-900 leading-tight">
                {user?.display_name || "Columbia Administrator"}
              </h2>
              <div className="text-xs text-slate-500 font-semibold">{user?.role || "Intelligence Lead"}</div>
            </div>
          </div>
        </div>

        {/* Form Body */}
        <form onSubmit={handleSave} className="p-8 pt-14 space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {/* Display Name */}
            <div className="space-y-1.5">
              <label className="text-xs font-bold text-slate-700 uppercase tracking-wider block">
                Display Name
              </label>
              <div className="relative">
                <UserIcon className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  className="w-full pl-10 pr-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs sm:text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-sky-500/20 focus:border-sky-500"
                />
              </div>
            </div>

            {/* Email (Read only) */}
            <div className="space-y-1.5">
              <label className="text-xs font-bold text-slate-700 uppercase tracking-wider block">
                Corporate Email
              </label>
              <div className="relative">
                <Mail className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
                <input
                  type="email"
                  value={user?.email || "employee@columbia.com"}
                  disabled
                  className="w-full pl-10 pr-4 py-2.5 bg-slate-100 border border-slate-200 rounded-xl text-xs sm:text-sm font-semibold text-slate-500 cursor-not-allowed"
                />
              </div>
            </div>

            {/* Avatar URL */}
            <div className="space-y-1.5">
              <label className="text-xs font-bold text-slate-700 uppercase tracking-wider block">
                Avatar Image URL
              </label>
              <div className="relative">
                <Camera className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  value={avatarUrl}
                  onChange={(e) => setAvatarUrl(e.target.value)}
                  placeholder="https://..."
                  className="w-full pl-10 pr-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs sm:text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-sky-500/20 focus:border-sky-500"
                />
              </div>
            </div>

            {/* Time Zone */}
            <div className="space-y-1.5">
              <label className="text-xs font-bold text-slate-700 uppercase tracking-wider block">
                Time Zone
              </label>
              <div className="relative">
                <Clock className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
                <select
                  value={timezone}
                  onChange={(e) => setTimezone(e.target.value)}
                  className="w-full pl-10 pr-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs sm:text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-sky-500/20 focus:border-sky-500 cursor-pointer"
                >
                  <option value="Asia/Kolkata">Asia/Kolkata (IST - UTC+05:30)</option>
                  <option value="UTC">UTC (Universal Coordinated Time)</option>
                  <option value="America/New_York">America/New_York (EST - UTC-05:00)</option>
                  <option value="America/Los_Angeles">America/Los_Angeles (PST - UTC-08:00)</option>
                </select>
              </div>
            </div>
          </div>

          {/* Preferences */}
          <div className="pt-4 border-t border-slate-100 space-y-4">
            <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider">
              System Preferences
            </h3>

            {/* Notifications Toggle */}
            <label className="flex items-center justify-between p-4 bg-slate-50/70 rounded-2xl border border-slate-200/80 cursor-pointer">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-sky-100 text-sky-600 flex items-center justify-center">
                  <Bell className="w-4 h-4" />
                </div>
                <div>
                  <div className="text-xs font-bold text-slate-900">Email Price Alert Notifications</div>
                  <div className="text-[11px] text-slate-500">
                    Receive daily digest when competitor prices undercut Columbia listed price.
                  </div>
                </div>
              </div>
              <input
                type="checkbox"
                checked={notifications}
                onChange={(e) => setNotifications(e.target.checked)}
                className="w-4 h-4 text-sky-500 rounded focus:ring-sky-500"
              />
            </label>

            {/* Theme Preference */}
            <div className="flex items-center justify-between p-4 bg-slate-50/70 rounded-2xl border border-slate-200/80">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-amber-100 text-amber-600 flex items-center justify-center">
                  <Sun className="w-4 h-4" />
                </div>
                <div>
                  <div className="text-xs font-bold text-slate-900">Theme Appearance</div>
                  <div className="text-[11px] text-slate-500">Select dashboard visual theme.</div>
                </div>
              </div>
              <div className="flex gap-1.5">
                <button
                  type="button"
                  onClick={() => setTheme("light")}
                  className={`px-3 py-1 rounded-lg text-xs font-bold transition-all ${
                    theme === "light"
                      ? "bg-[#079FE0] text-white shadow-2xs"
                      : "bg-white border text-slate-600"
                  }`}
                >
                  Light
                </button>
                <button
                  type="button"
                  onClick={() => setTheme("dark")}
                  className={`px-3 py-1 rounded-lg text-xs font-bold transition-all ${
                    theme === "dark"
                      ? "bg-[#079FE0] text-white shadow-2xs"
                      : "bg-white border text-slate-600"
                  }`}
                >
                  Dark
                </button>
              </div>
            </div>
          </div>

          {/* Form Actions */}
          <div className="pt-6 border-t border-slate-100 flex items-center justify-between">
            <button
              type="button"
              onClick={handleLogout}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-rose-200 bg-rose-50 hover:bg-rose-100 text-rose-700 text-xs font-bold transition-colors cursor-pointer"
            >
              <LogOut className="w-4 h-4" />
              <span>Sign Out of VANTIS</span>
            </button>

            <button
              type="submit"
              disabled={isLoading}
              className="inline-flex items-center gap-2 px-6 py-2.5 bg-[#079FE0] hover:bg-[#068ec8] text-white rounded-xl text-xs font-bold shadow-xs transition-all cursor-pointer"
            >
              <Save className="w-4 h-4" />
              <span>{isLoading ? "Saving..." : "Save Preferences"}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default ProfilePage;
