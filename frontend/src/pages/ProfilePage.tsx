import React, { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  User as UserIcon,
  Shield,
  KeyRound,
  Camera,
  CheckCircle2,
  AlertCircle,
  LogOut,
  Save,
} from "lucide-react";
import authService from "../services/authService";
import { User } from "../types";

export const ProfilePage: React.FC = () => {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [user, setUser] = useState<User | null>(null);
  const [avatarUrl, setAvatarUrl] = useState("");
  const [displayName, setDisplayName] = useState("");

  // Password reset state
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isResettingPassword, setIsResettingPassword] = useState(false);

  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isUploadingAvatar, setIsUploadingAvatar] = useState(false);

  useEffect(() => {
    loadUser();
  }, []);

  const loadUser = async () => {
    try {
      const u = await authService.getCurrentUser();
      setUser(u);
      setAvatarUrl(u.avatar_url || "");
      setDisplayName(u.display_name || u.username);
    } catch {
      const saved = authService.getSavedUser();
      if (saved) {
        setUser(saved);
        setAvatarUrl(saved.avatar_url || "");
        setDisplayName(saved.display_name || saved.username);
      }
    }
  };

  const handleAvatarFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploadingAvatar(true);
    setErrorMessage(null);
    try {
      const res = await authService.uploadAvatar(file);
      setAvatarUrl(res.avatar_url);
      setSuccessMessage("Avatar image successfully updated.");
      setTimeout(() => setSuccessMessage(null), 3500);
      loadUser();
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to upload avatar image.");
    } finally {
      setIsUploadingAvatar(false);
    }
  };

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      const updated = await authService.updateProfile({
        display_name: displayName,
        avatar_url: avatarUrl,
      });
      setUser(updated);
      setSuccessMessage("Profile preferences successfully saved.");
      setTimeout(() => setSuccessMessage(null), 3500);
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to save profile.");
    }
  };

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    setSuccessMessage(null);

    if (!newPassword || newPassword.length < 4) {
      setErrorMessage("New password must be at least 4 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setErrorMessage("New passwords do not match.");
      return;
    }

    setIsResettingPassword(true);
    try {
      await authService.resetPassword(newPassword, currentPassword || undefined);
      setSuccessMessage("Password successfully updated!");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setTimeout(() => setSuccessMessage(null), 3500);
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to reset password.");
    } finally {
      setIsResettingPassword(false);
    }
  };

  const handleLogout = async () => {
    await authService.logout();
    navigate("/login");
  };

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-8 py-8 space-y-8 select-none">
      {/* Page Title */}
      <div>
        <h1 className="text-2xl sm:text-3xl font-black text-slate-900 tracking-tight">
          User Profile &amp; Security
        </h1>
        <p className="text-xs sm:text-sm text-slate-500 font-semibold mt-1">
          Manage your account profile picture and update your password.
        </p>
      </div>

      {/* Messages */}
      {successMessage && (
        <div className="p-4 rounded-2xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs sm:text-sm font-bold flex items-center gap-2 animate-in fade-in">
          <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-600" />
          <span>{successMessage}</span>
        </div>
      )}
      {errorMessage && (
        <div className="p-4 rounded-2xl bg-rose-50 border border-rose-200 text-rose-800 text-xs sm:text-sm font-bold flex items-center gap-2 animate-in fade-in">
          <AlertCircle className="w-4 h-4 shrink-0 text-rose-600" />
          <span>{errorMessage}</span>
        </div>
      )}

      {/* Profile Card */}
      <div className="bg-white rounded-3xl border border-slate-200/90 shadow-sm overflow-hidden">
        {/* Banner with Avatar Overlay */}
        <div className="h-28 bg-[#079FE0] relative px-6">
          <div className="absolute -bottom-10 left-8 flex items-end gap-4">
            <div className="relative group">
              <div className="w-20 h-20 rounded-2xl bg-white p-1 ring-4 ring-white shadow-md overflow-hidden flex items-center justify-center">
                {avatarUrl || user?.avatar_url ? (
                  <img
                    src={avatarUrl || user?.avatar_url}
                    alt={user?.username}
                    className="w-full h-full object-cover rounded-xl"
                  />
                ) : (
                  <div className="w-full h-full bg-sky-100 text-sky-800 font-black text-xl flex items-center justify-center rounded-xl">
                    {user?.username?.slice(0, 2).toUpperCase() || "CV"}
                  </div>
                )}
              </div>

              {/* Camera Icon Overlay to Upload/Change Avatar */}
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploadingAvatar}
                className="absolute inset-0 rounded-2xl bg-black/40 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
                title="Change Avatar Image"
              >
                <Camera className="w-6 h-6" />
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                onChange={handleAvatarFileChange}
                className="hidden"
              />
            </div>

            <div className="mb-3">
              <h2 className="text-lg font-black text-slate-900 leading-tight">
                {user?.display_name || user?.username}
              </h2>
              <div className="text-xs text-slate-500 font-bold">
                @{user?.username} • {user?.role || "Columbia Specialist"}
              </div>
            </div>
          </div>
        </div>

        {/* User Details Form */}
        <form onSubmit={handleSaveProfile} className="p-8 pt-16 space-y-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            {/* Username (Fixed / Read-only) */}
            <div className="space-y-1.5">
              <label className="text-xs font-bold text-slate-700 uppercase tracking-wider block">
                Username (Primary Key)
              </label>
              <div className="relative">
                <UserIcon className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  value={user?.username || ""}
                  disabled
                  className="w-full pl-10 pr-4 py-2.5 bg-slate-100 border border-slate-200 rounded-xl text-xs sm:text-sm font-bold text-slate-500 cursor-not-allowed"
                />
              </div>
              <p className="text-[11px] text-slate-400 font-medium">Username cannot be changed.</p>
            </div>

            {/* Display Name */}
            <div className="space-y-1.5">
              <label className="text-xs font-bold text-slate-700 uppercase tracking-wider block">
                Display Name
              </label>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs sm:text-sm font-bold text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#079FE0]/20 focus:border-[#079FE0]"
              />
            </div>

            {/* Avatar URL / Direct Link */}
            <div className="sm:col-span-2 space-y-1.5">
              <label className="text-xs font-bold text-slate-700 uppercase tracking-wider block">
                Avatar Image Link or Upload
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={avatarUrl}
                  onChange={(e) => setAvatarUrl(e.target.value)}
                  placeholder="https://... or click avatar icon above to upload"
                  className="flex-1 px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs sm:text-sm font-medium text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#079FE0]/20 focus:border-[#079FE0]"
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="px-4 py-2.5 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold rounded-xl transition-colors cursor-pointer flex items-center gap-1.5"
                >
                  <Camera className="w-4 h-4" />
                  <span>Upload</span>
                </button>
              </div>
            </div>
          </div>

          <div className="flex justify-end pt-2">
            <button
              type="submit"
              className="px-5 py-2.5 bg-[#079FE0] hover:bg-[#068ec8] text-white text-xs sm:text-sm font-bold rounded-xl transition-colors cursor-pointer shadow-xs flex items-center gap-2"
            >
              <Save className="w-4 h-4" />
              <span>Save Profile</span>
            </button>
          </div>
        </form>
      </div>

      {/* Password Reset Section */}
      <div className="bg-white rounded-3xl border border-slate-200/90 shadow-sm p-8 space-y-6">
        <div className="flex items-center gap-3 pb-4 border-b border-slate-100">
          <div className="w-10 h-10 rounded-xl bg-amber-50 text-amber-600 flex items-center justify-center border border-amber-100">
            <KeyRound className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-base sm:text-lg font-black text-slate-900">
              Reset Password
            </h2>
            <p className="text-xs text-slate-500 font-medium">
              Update password for @{user?.username || "user"} with secure SHA-256 JWT encryption.
            </p>
          </div>
        </div>

        <form onSubmit={handleResetPassword} className="space-y-4 max-w-md">
          <div className="space-y-1.5">
            <label className="text-xs font-bold text-slate-700 block">
              Current Password (Optional if newly assigned)
            </label>
            <input
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              placeholder="Current password"
              className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs sm:text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#079FE0]/20 focus:border-[#079FE0]"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-bold text-slate-700 block">
              New Password
            </label>
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="New password (min 4 characters)"
              required
              className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs sm:text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#079FE0]/20 focus:border-[#079FE0]"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-bold text-slate-700 block">
              Confirm New Password
            </label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Confirm new password"
              required
              className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs sm:text-sm font-semibold text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#079FE0]/20 focus:border-[#079FE0]"
            />
          </div>

          <button
            type="submit"
            disabled={isResettingPassword}
            className="mt-2 px-6 py-2.5 bg-slate-900 hover:bg-slate-800 text-white text-xs sm:text-sm font-bold rounded-xl transition-colors cursor-pointer shadow-xs disabled:opacity-50"
          >
            {isResettingPassword ? "Updating..." : "Update Password"}
          </button>
        </form>
      </div>

      {/* Sign Out Card */}
      <div className="flex justify-between items-center p-6 bg-rose-50/50 rounded-3xl border border-rose-100">
        <div>
          <h3 className="text-sm font-bold text-rose-900">Sign Out</h3>
          <p className="text-xs text-rose-600 font-medium">Terminate current authenticated session.</p>
        </div>
        <button
          onClick={handleLogout}
          className="px-4 py-2 bg-rose-600 hover:bg-rose-700 text-white text-xs font-bold rounded-xl transition-colors cursor-pointer flex items-center gap-1.5 shadow-xs"
        >
          <LogOut className="w-4 h-4" />
          <span>Sign Out</span>
        </button>
      </div>
    </div>
  );
};

export default ProfilePage;
