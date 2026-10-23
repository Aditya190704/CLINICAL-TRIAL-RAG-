import React, { useState } from "react";
import { useAuth } from "./AuthContext";

function readableAuthError(error) {
  const code = error?.code || "";
  const messages = {
    "auth/email-already-in-use": "An account already exists for this email.",
    "auth/invalid-email": "Enter a valid email address.",
    "auth/invalid-credential": "Email or password is incorrect.",
    "auth/user-disabled": "This account is disabled. Contact your application support team.",
    "auth/weak-password": "Use a password with at least 6 characters.",
    "auth/too-many-requests": "Too many attempts. Wait a moment and try again.",
    "auth/network-request-failed": "Network error. Check your connection and retry.",
  };
  return messages[code] || error?.message || "Authentication failed. Please try again.";
}

export default function AuthScreen() {
  const { signIn, signUp, configured, error: profileError, retryProfile } = useAuth();
  const [mode, setMode] = useState("login");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const isSignup = mode === "signup";

  const submit = async (event) => {
    event.preventDefault();
    setError("");
    const cleanEmail = email.trim();
    if (isSignup && !displayName.trim()) return setError("Enter your name.");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanEmail)) return setError("Enter a valid email address.");
    if (password.length < 6) return setError("Password must be at least 6 characters.");
    setBusy(true);
    try {
      if (isSignup) await signUp(displayName.trim(), cleanEmail, password);
      else await signIn(cleanEmail, password);
    } catch (submitError) {
      setError(readableAuthError(submitError));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="auth-title">
        <div className="auth-brand-mark" aria-hidden="true">CT</div>
        <p className="auth-eyebrow">CLINICAL TRIAL MATCHER</p>
        <h1 id="auth-title">{isSignup ? "Create your technician account" : "Sign in to your workspace"}</h1>
        <p className="auth-subtitle">Secure access for clinical technicians.</p>

        {!configured ? (
          <div className="auth-alert" role="alert">
            Firebase web configuration is missing. Set the VITE_FIREBASE_* values in frontend/.env and restart Vite.
          </div>
        ) : (
          <form className="auth-form" onSubmit={submit}>
            {isSignup && (
              <label>
                Name
                <input autoComplete="name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} maxLength={100} required />
              </label>
            )}
            <label>
              Email
              <input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </label>
            <label>
              Password
              <input type="password" autoComplete={isSignup ? "new-password" : "current-password"} value={password} onChange={(e) => setPassword(e.target.value)} minLength={6} required />
            </label>
            {(error || profileError) && <div className="auth-alert" role="alert">{error || profileError}</div>}
            {profileError && (
              <button className="auth-secondary-button" type="button" onClick={retryProfile}>Retry loading profile</button>
            )}
            <button className="auth-submit" type="submit" disabled={busy}>
              {busy ? "Please wait…" : isSignup ? "Create account" : "Sign in"}
            </button>
          </form>
        )}

        {configured && !profileError && (
          <p className="auth-switch">
            {isSignup ? "Already have an account?" : "New clinical technician?"}{" "}
            <button type="button" onClick={() => { setMode(isSignup ? "login" : "signup"); setError(""); }}>
              {isSignup ? "Sign in" : "Create account"}
            </button>
          </p>
        )}
        <p className="auth-role-note">Application access is assigned as Clinical Technician.</p>
      </section>
    </main>
  );
}
