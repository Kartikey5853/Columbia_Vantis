import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Eye, EyeOff, Lock, User as UserIcon } from "lucide-react";
import VantisLogo from "../components/brand/VantisLogo";
import SplashScreen from "../components/layout/SplashScreen";
import authService from "../services/authService";

export const LoginPage: React.FC = () => {
  const navigate = useNavigate();
  const [username, setUsername] = useState("kartikey");
  const [password, setPassword] = useState("kartikey123");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username || !password) {
      setErrorMessage("Please enter both username and password.");
      return;
    }

    setIsLoading(true);
    setErrorMessage(null);

    try {
      await authService.login(username, password, rememberMe);
      // Pass state to show splash loading screen
      navigate("/home", { state: { justLoggedIn: true } });
    } catch (err: any) {
      setErrorMessage(err.message || "Invalid username or password. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <>
      {isLoading && <SplashScreen maxWaitSeconds={90} />}
      <div
        className="min-h-screen bg-cover bg-center bg-no-repeat flex items-center justify-center p-4 sm:p-6 select-none relative"
        style={{ backgroundImage: "url('/login-bg.png')" }}
      >
      {/* Subtle overlay for contrast */}
      <div className="absolute inset-0 bg-slate-900/10 pointer-events-none" />

      {/* Login Box */}
      <div className="relative z-10 w-full max-w-sm bg-white/95 backdrop-blur-md rounded-3xl border border-slate-200/90 shadow-2xl p-7 sm:p-8">
        {/* Columbia VANTIS Logo INSIDE the box */}
        <div className="flex justify-center mb-6">
          <img
            src="/vantis_big_logo.png"
            alt="Columbia Sportswear"
            className="h-20 sm:h-24 w-auto object-contain drop-shadow-none"
          />
        </div>
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Error Banner */}
            {errorMessage && (
              <div className="p-3 rounded-xl bg-rose-50 border border-rose-100 text-rose-700 text-xs font-semibold">
                {errorMessage}
              </div>
            )}

            {/* Username Input */}
            <div className="space-y-1">
              <label className="text-xs font-bold text-slate-700 block">
                Username
              </label>
              <div className="relative">
                <UserIcon className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="Username"
                  required
                  autoFocus
                  className="w-full pl-9 pr-3 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-[#079FE0]/20 focus:border-[#079FE0] text-slate-900"
                />
              </div>
            </div>

            {/* Password Input */}
            <div className="space-y-1">
              <label className="text-xs font-bold text-slate-700 block">
                Password
              </label>
              <div className="relative">
                <Lock className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Password"
                  required
                  className="w-full pl-9 pr-9 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-[#079FE0]/20 focus:border-[#079FE0] text-slate-900"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="p-1 text-slate-400 hover:text-slate-600 absolute right-2.5 top-1/2 -translate-y-1/2"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* Remember Me */}
            <div className="flex items-center justify-between pt-1">
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.target.checked)}
                  className="w-4 h-4 rounded text-[#079FE0] border-slate-300 focus:ring-[#079FE0] focus:ring-offset-0"
                />
                <span className="text-xs font-medium text-slate-600">Remember me</span>
              </label>
            </div>

            {/* Sign In Button */}
            <button
              type="submit"
              disabled={isLoading}
              className="w-full mt-2 py-2.5 px-4 bg-[#079FE0] hover:bg-[#068ec8] disabled:opacity-50 text-white font-bold text-sm rounded-xl transition-colors shadow-xs cursor-pointer"
            >
              {isLoading ? "Signing in..." : "Sign in"}
            </button>
          </form>
      </div>
    </div>
    </>
  );
};

export default LoginPage;
