import React, { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import {
  User as UserIcon,
  KeyRound,
  Camera,
  CheckCircle2,
  AlertCircle,
  LogOut,
  Save,
  Trash2,
  Upload,
} from "lucide-react";
import authService from "../services/authService";
import { User } from "../types";

export const ProfilePage: React.FC = () => {
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [user, setUser] = useState<User | null>(null);
  const [avatarUrl, setAvatarUrl] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [avatarLoadError, setAvatarLoadError] = useState(false);

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
      setAvatarLoadError(false);
    } catch {
      const saved = authService.getSavedUser();
      if (saved) {
        setUser(saved);
        setAvatarUrl(saved.avatar_url || "");
        setDisplayName(saved.display_name || saved.username);
        setAvatarLoadError(false);
      }
    }
  };

  const handleAvatarFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploadingAvatar(true);
    setErrorMessage(null);

    const reader = new FileReader();
    reader.onload = (event) => {
      const img = new Image();
      img.onload = async () => {
        // Downscale image to max 256x256 to create lightweight base64 data URL
        const canvas = document.createElement("canvas");
        const maxDim = 256;
        let w = img.width;
        let h = img.height;
        if (w > h) {
          if (w > maxDim) {
            h = Math.round((h * maxDim) / w);
            w = maxDim;
          }
        } else {
          if (h > maxDim) {
            w = Math.round((w * maxDim) / h);
            h = maxDim;
          }
        }
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext("2d");
        if (ctx) {
          ctx.drawImage(img, 0, 0, w, h);
          const dataUrl = canvas.toDataURL("image/jpeg", 0.85);
          setAvatarUrl(dataUrl);
          setAvatarLoadError(false);
          try {
            const updatedUser = await authService.updateProfile({ avatar_url: dataUrl });
            if (updatedUser) {
              setUser(updatedUser);
              localStorage.setItem("vantis_user", JSON.stringify(updatedUser));
              window.dispatchEvent(new Event("storage"));
              window.dispatchEvent(new CustomEvent("vantis_user_updated", { detail: updatedUser }));
              setSuccessMessage("Profile photo updated and saved to database successfully!");
              setTimeout(() => setSuccessMessage(null), 3500);
            }
          } catch (err: any) {
            setErrorMessage(err.message || "Failed to save avatar photo to database.");
          }
        }
        setIsUploadingAvatar(false);
      };
      img.onerror = () => {
        setErrorMessage("Invalid image format. Please select a PNG or JPG.");
        setIsUploadingAvatar(false);
      };
      img.src = event.target?.result as string;
    };
    reader.onerror = () => {
      setErrorMessage("Error reading file from disk.");
      setIsUploadingAvatar(false);
    };
    reader.readAsDataURL(file);
  };

  const handleRemoveAvatar = async () => {
    setAvatarUrl("");
    setAvatarLoadError(false);
    try {
      const updatedUser = await authService.updateProfile({ avatar_url: "" });
      if (updatedUser) {
        setUser(updatedUser);
        localStorage.setItem("vantis_user", JSON.stringify(updatedUser));
        window.dispatchEvent(new Event("storage"));
        window.dispatchEvent(new CustomEvent("vantis_user_updated", { detail: updatedUser }));
        setSuccessMessage("Profile photo removed.");
        setTimeout(() => setSuccessMessage(null), 3500);
      }
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to remove avatar.");
    }
  };

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    setSuccessMessage(null);
    try {
      const updatedUser = await authService.updateProfile({
        display_name: displayName,
        avatar_url: avatarUrl,
      });
      if (updatedUser) {
        setUser(updatedUser);
        localStorage.setItem("vantis_user", JSON.stringify(updatedUser));
        window.dispatchEvent(new Event("storage"));
        window.dispatchEvent(new CustomEvent("vantis_user_updated", { detail: updatedUser }));
        setSuccessMessage("Profile details successfully saved to database.");
        setTimeout(() => setSuccessMessage(null), 3500);
      }
    } catch (err: any) {
      setErrorMessage(err.message || "Failed to save profile changes.");
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

  const userInitial = user?.username ? user.username.charAt(0).toUpperCase() : "U";

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-8 py-8 space-y-8 select-none">
      {/* Page Title */}
      <div>
        <h1 className="text-2xl sm:text-3xl font-black text-slate-900 tracking-tight">
          User Profile &amp; Settings
        </h1>
        <p className="text-xs sm:text-sm text-slate-500 font-semibold mt-1">
          Update profile information, upload avatar picture, and manage your password.
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
        {/* Clean Profile Header (No blue banner, no job title) */}
        <div className="p-8 pb-4 border-b border-slate-100 flex flex-col sm:flex-row sm:items-center gap-6">
          <div className="relative group shrink-0">
            <div className="w-20 h-20 rounded-2xl bg-slate-50 p-1 border border-slate-200 shadow-xs overflow-hidden flex items-center justify-center">
              {avatarUrl && !avatarUrl.includes("unsplash.com") && !avatarLoadError ? (
                <img
                  src={avatarUrl}
                  alt={user?.username}
                  className="w-full h-full object-cover rounded-xl"
                  onError={() => setAvatarLoadError(true)}
                />
              ) : (
                <div className="w-full h-full bg-slate-900 text-white font-black text-2xl flex items-center justify-center rounded-xl shadow-inner">
                  {userInitial}
                </div>
              )}
            </div>

            {/* Camera Icon Overlay to Upload/Change Avatar */}
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isUploadingAvatar}
              className="absolute inset-0 rounded-2xl bg-black/60 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
              title="Change Profile Photo"
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

          <div>
            <h2 className="text-xl font-black text-slate-900 leading-tight">
              {user?.display_name || user?.username}
            </h2>
            <div className="text-xs text-slate-400 font-mono mt-0.5">
              @{user?.username}
            </div>
          </div>
        </div>

        {/* User Details Form */}
        <form onSubmit={handleSaveProfile} className="p-8 pt-6 space-y-6">
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
              <p className="text-[11px] text-slate-400 font-medium">Username is fixed.</p>
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

            {/* Avatar Photo Actions */}
            <div className="sm:col-span-2 space-y-2 pt-1">
              <label className="text-xs font-bold text-slate-700 uppercase tracking-wider block">
                Profile Photo
              </label>
              <div className="flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isUploadingAvatar}
                  className="px-4 py-2.5 bg-[#079FE0] hover:bg-[#068ec8] text-white text-xs sm:text-sm font-bold rounded-xl transition-colors cursor-pointer flex items-center gap-2 shadow-xs"
                >
                  <Upload className="w-4 h-4" />
                  <span>{isUploadingAvatar ? "Processing..." : "Upload New Photo"}</span>
                </button>
                {avatarUrl && (
                  <button
                    type="button"
                    onClick={handleRemoveAvatar}
                    className="px-3.5 py-2.5 border border-slate-200 bg-white hover:bg-slate-50 text-slate-600 text-xs sm:text-sm font-semibold rounded-xl transition-colors cursor-pointer flex items-center gap-1.5"
                  >
                    <Trash2 className="w-4 h-4 text-rose-500" />
                    <span>Reset to Initials</span>
                  </button>
                )}
              </div>
              <p className="text-[11px] text-slate-400 font-medium">
                Supports PNG, JPG, or WEBP. Image is automatically compressed and saved directly to your account.
              </p>
            </div>
          </div>

          <div className="flex justify-end pt-2">
            <button
              type="submit"
              className="px-6 py-2.5 bg-[#079FE0] hover:bg-[#068ec8] text-white text-xs sm:text-sm font-bold rounded-xl transition-colors cursor-pointer shadow-xs flex items-center gap-2"
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
              Update password for @{user?.username || "user"}.
            </p>
          </div>
        </div>

        <form onSubmit={handleResetPassword} className="space-y-4 max-w-md">
          <div className="space-y-1.5">
            <label className="text-xs font-bold text-slate-700 block">
              Current Password (Optional)
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
