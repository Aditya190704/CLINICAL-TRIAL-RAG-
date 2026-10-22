import { useState, useEffect, useCallback, useMemo } from "react";
import {
  loadSessionsFromStorage,
  saveSessionsToStorage,
  loadActiveSessionId,
  saveActiveSessionId,
  clearAllStorage,
} from "../utils/storage";
import { generateSessionTitle } from "../utils/formatters";

/**
 * Generate a unique session identifier.
 */
function createSessionId() {
  return `session_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
}

/**
 * Create a fresh blank session object.
 */
function createBlankSession(initialCase = "") {
  const now = Date.now();
  return {
    id: createSessionId(),
    title: initialCase ? generateSessionTitle(initialCase) : "New Patient Session",
    patientCase: initialCase,
    data: null,
    activeTab: 0,
    chatHistory: [],
    createdAt: now,
    updatedAt: now,
  };
}

/**
 * Custom hook for complete Session Management via sessionStorage.
 */
export function useSessionManager() {
  const [sessions, setSessions] = useState(() => {
    const loaded = loadSessionsFromStorage();
    if (loaded && loaded.length > 0) {
      return loaded;
    }
    const initial = createBlankSession();
    saveSessionsToStorage([initial]);
    return [initial];
  });

  const [activeSessionId, setActiveSessionId] = useState(() => {
    const savedActiveId = loadActiveSessionId();
    const loaded = loadSessionsFromStorage();
    if (savedActiveId && loaded.some((s) => s.id === savedActiveId)) {
      return savedActiveId;
    }
    if (loaded && loaded.length > 0) {
      return loaded[0].id;
    }
    return null;
  });

  // Ensure activeSessionId is valid and synced
  useEffect(() => {
    if (!activeSessionId && sessions.length > 0) {
      const nextId = sessions[0].id;
      setActiveSessionId(nextId);
      saveActiveSessionId(nextId);
    } else if (activeSessionId) {
      saveActiveSessionId(activeSessionId);
    }
  }, [activeSessionId, sessions]);

  // Keep sessionStorage in sync whenever sessions state changes
  useEffect(() => {
    saveSessionsToStorage(sessions);
  }, [sessions]);

  // Current active session object
  const activeSession = useMemo(() => {
    return (
      sessions.find((s) => s.id === activeSessionId) ||
      sessions[0] ||
      createBlankSession()
    );
  }, [sessions, activeSessionId]);

  /**
   * Switch active session by ID.
   */
  const switchSession = useCallback((id) => {
    const target = sessions.find((s) => s.id === id);
    if (target) {
      setActiveSessionId(id);
      saveActiveSessionId(id);
      return target;
    }
    return null;
  }, [sessions]);

  /**
   * Create a new blank session and make it active.
   */
  const createNewSession = useCallback((initialCase = "") => {
    const newSession = createBlankSession(initialCase);
    setSessions((prev) => [newSession, ...prev]);
    setActiveSessionId(newSession.id);
    saveActiveSessionId(newSession.id);
    return newSession;
  }, []);

  /**
   * Update fields on the currently active session.
   */
  const updateActiveSession = useCallback(
    (patch) => {
      setSessions((prev) =>
        prev.map((s) => {
          if (s.id !== activeSessionId) return s;

          const updated = {
            ...s,
            ...patch,
            updatedAt: Date.now(),
          };

          // Auto-generate a smart title if user has a default title
          // and a patient case or clinical profile was provided
          const isGeneratedTitle =
            !s.title ||
            s.title === "New Patient Session" ||
            s.title.startsWith("Patient Case") ||
            /^\d{1,3}yo\s*[•·]/i.test(s.title) ||
            /^\d{1,3}[-\s]?year[-\s]?old\b/i.test(s.title);
          if (
            isGeneratedTitle &&
            (patch.patientCase || patch.data?.patient_profile)
          ) {
            const newTitle = generateSessionTitle(
              patch.patientCase ?? s.patientCase,
              patch.data?.patient_profile ?? s.data?.patient_profile
            );
            if (newTitle && newTitle !== "New Patient Session") {
              updated.title = newTitle;
            }
          }

          return updated;
        })
      );
    },
    [activeSessionId]
  );

  /**
   * Rename a specific session.
   */
  const renameSession = useCallback((id, newTitle) => {
    if (!newTitle || !newTitle.trim()) return;
    const cleanTitle = newTitle.trim().slice(0, 80);
    setSessions((prev) =>
      prev.map((s) => (s.id === id ? { ...s, title: cleanTitle, updatedAt: Date.now() } : s))
    );
  }, []);

  /**
   * Delete a specific session.
   */
  const deleteSession = useCallback(
    (id) => {
      setSessions((prev) => {
        const remaining = prev.filter((s) => s.id !== id);
        if (remaining.length === 0) {
          const fresh = createBlankSession();
          setActiveSessionId(fresh.id);
          saveActiveSessionId(fresh.id);
          return [fresh];
        }

        if (activeSessionId === id) {
          const nextActive = remaining[0];
          setActiveSessionId(nextActive.id);
          saveActiveSessionId(nextActive.id);
        }
        return remaining;
      });
    },
    [activeSessionId]
  );

  /**
   * Clear all sessions and start with one fresh blank session.
   */
  const clearAllSessions = useCallback(() => {
    clearAllStorage();
    const fresh = createBlankSession();
    setSessions([fresh]);
    setActiveSessionId(fresh.id);
    saveActiveSessionId(fresh.id);
  }, []);

  return {
    sessions,
    activeSessionId,
    activeSession,
    switchSession,
    createNewSession,
    updateActiveSession,
    renameSession,
    deleteSession,
    clearAllSessions,
  };
}

