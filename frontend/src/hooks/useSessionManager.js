import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
  clearRemoteSessions,
  createSession as createRemoteSession,
  deleteRemoteSession,
  getSession,
  listSessions,
  renameRemoteSession,
} from "../api";
import { clearAllStorage } from "../utils/storage";

function normalizeSession(session) {
  return {
    id: session.id,
    title: session.title || "New Patient Session",
    patientCase: session.searchQuery || "",
    data: session.data || null,
    activeTab: 0,
    chatHistory: session.chatHistory || [],
    createdAt: session.createdAt || Date.now(),
    updatedAt: session.updatedAt || Date.now(),
  };
}

export function useSessionManager(user) {
  const [sessions, setSessions] = useState([]);
  const [activeSessionId, setActiveSessionId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [loadingSessionId, setLoadingSessionId] = useState(null);
  const switchRequest = useRef(0);

  useEffect(() => {
    let mounted = true;
    clearAllStorage(); // remove legacy per-tab cases/chat before loading user data
    setSessions([]);
    setActiveSessionId(null);
    setLoading(true);
    setError("");
    (async () => {
      try {
        let loaded = await listSessions();
        if (!Array.isArray(loaded)) loaded = [];
        if (loaded.length === 0) {
          loaded = [await createRemoteSession()];
        }
        if (!mounted) return;
        const normalized = loaded.map(normalizeSession);
        setSessions(normalized);
        const first = normalized[0];
        setActiveSessionId(first.id);
        const details = await getSession(first.id);
        if (mounted) {
          setSessions((current) => current.map((item) => item.id === first.id
            ? { ...item, ...normalizeSession(details) }
            : item));
        }
      } catch (loadError) {
        if (mounted) setError(loadError.message || "Could not load saved sessions.");
      } finally {
        if (mounted) setLoading(false);
      }
    })();
    return () => { mounted = false; };
  }, [user?.firebaseUser?.uid]);

  const activeSession = useMemo(
    () => sessions.find((session) => session.id === activeSessionId) || null,
    [sessions, activeSessionId],
  );

  const switchSession = useCallback(async (id) => {
    const requestId = ++switchRequest.current;
    setLoadingSessionId(id);
    setError("");
    try {
      const detail = await getSession(id);
      if (requestId !== switchRequest.current) return;
      setSessions((current) => current.map((item) => item.id === id
        ? { ...item, ...normalizeSession(detail) }
        : item));
      setActiveSessionId(id);
      return true;
    } catch (loadError) {
      if (requestId === switchRequest.current) setError(loadError.message || "Could not open this session.");
      return false;
    } finally {
      if (requestId === switchRequest.current) setLoadingSessionId(null);
    }
  }, []);

  const createNewSession = useCallback(async (title) => {
    switchRequest.current += 1;
    setLoadingSessionId(null);
    setError("");
    try {
      const created = normalizeSession(await createRemoteSession(title));
      setSessions((current) => [created, ...current]);
      setActiveSessionId(created.id);
      setError("");
      return created;
    } catch (createError) {
      setError(createError.message || "Could not create a session.");
      throw createError;
    }
  }, []);

  const updateSession = useCallback((id, patch) => {
    if (!id) return;
    const { touch = false, ...sessionPatch } = patch;
    setSessions((current) => {
      const next = current.map((session) => {
        if (session.id !== id) return session;
        const updated = { ...session, ...sessionPatch, updatedAt: new Date().toISOString() };
        if (sessionPatch.title && sessionPatch.title !== session.title) {
          renameRemoteSession(id, sessionPatch.title).catch((renameError) => {
            setError(renameError.message || "Could not save the session name.");
          });
        }
        return updated;
      });
      if (touch || sessionPatch.data || sessionPatch.chatHistory || sessionPatch.title) {
        next.sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
      }
      return next;
    });
  }, []);

  const updateActiveSession = useCallback((patch) => {
    updateSession(activeSessionId, patch);
  }, [activeSessionId, updateSession]);

  const renameSession = useCallback(async (id, title) => {
    const cleanTitle = title?.trim().slice(0, 100);
    if (!cleanTitle) return;
    try {
      await renameRemoteSession(id, cleanTitle);
      setSessions((current) => {
        const renamed = current.map((item) => item.id === id
          ? { ...item, title: cleanTitle, updatedAt: new Date().toISOString() }
          : item);
        return renamed.sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
      });
    } catch (renameError) {
      setError(renameError.message || "Could not rename this session.");
    }
  }, []);

  const deleteSession = useCallback(async (id) => {
    try {
      await deleteRemoteSession(id);
      let remaining = sessions.filter((item) => item.id !== id);
      if (remaining.length === 0) remaining = [normalizeSession(await createRemoteSession())];
      setSessions(remaining);
      if (activeSessionId === id) setActiveSessionId(remaining[0].id);
    } catch (deleteError) {
      setError(deleteError.message || "Could not delete this session.");
    }
  }, [sessions, activeSessionId]);

  const clearAllSessions = useCallback(async () => {
    try {
      await clearRemoteSessions();
      const fresh = normalizeSession(await createRemoteSession());
      setSessions([fresh]);
      setActiveSessionId(fresh.id);
    } catch (clearError) {
      setError(clearError.message || "Could not clear saved sessions.");
    }
  }, []);

  return {
    sessions,
    activeSessionId,
    activeSession,
    loading,
    loadingSessionId,
    error,
    switchSession,
    createNewSession,
    updateActiveSession,
    updateSession,
    renameSession,
    deleteSession,
    clearAllSessions,
  };
}
