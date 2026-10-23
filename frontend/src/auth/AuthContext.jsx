import React, { createContext, useContext, useEffect, useMemo, useState } from "react";
import {
  createUserWithEmailAndPassword,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  signOut,
  updateProfile,
} from "firebase/auth";
import { API_BASE, initializeProfile } from "../api";
import { auth, isFirebaseConfigured } from "../firebase";

const AuthContext = createContext(null);

async function loadProfile(firebaseUser) {
  const token = await firebaseUser.getIdToken();
  const response = await fetch(`${API_BASE}/api/auth/profile`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new Error(response.status === 503
      ? "User profile storage is unavailable. Check Firebase Admin and Firestore setup."
      : "Could not load your user profile. Please retry sign-in.");
  }
  return response.json();
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!auth) {
      setLoading(false);
      return undefined;
    }
    let mounted = true;
    const unsubscribe = onAuthStateChanged(auth, async (firebaseUser) => {
      setUser(null);
      setError("");
      if (!firebaseUser) {
        setLoading(false);
        return;
      }
      setLoading(true);
      try {
        const profile = await loadProfile(firebaseUser);
        if (mounted) setUser({ firebaseUser, profile });
      } catch (loadError) {
        if (mounted) setError(loadError.message || "Could not load your profile.");
      } finally {
        if (mounted) setLoading(false);
      }
    });
    return () => {
      mounted = false;
      unsubscribe();
    };
  }, []);

  const value = useMemo(() => ({
    user,
    loading,
    error,
    configured: isFirebaseConfigured,
    signIn: (email, password) => signInWithEmailAndPassword(auth, email, password),
    signUp: async (displayName, email, password) => {
      const credential = await createUserWithEmailAndPassword(auth, email, password);
      await updateProfile(credential.user, { displayName });
      await credential.user.getIdToken(true);
      const profile = await initializeProfile(displayName);
      setUser({ firebaseUser: credential.user, profile });
      return credential;
    },
    signOut: () => signOut(auth),
    retryProfile: async () => {
      if (!auth?.currentUser) return;
      setLoading(true);
      setError("");
      try {
        const profile = await loadProfile(auth.currentUser);
        setUser({ firebaseUser: auth.currentUser, profile });
      } catch (loadError) {
        setError(loadError.message || "Could not load your profile.");
      } finally {
        setLoading(false);
      }
    },
  }), [user, loading, error]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used within AuthProvider.");
  return value;
}
