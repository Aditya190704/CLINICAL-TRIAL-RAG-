import React, { useState, useMemo } from "react";
import SessionItem from "./SessionItem";
import RenameModal from "./RenameModal";
import ConfirmDialog from "../ui/ConfirmDialog";
import Button from "../ui/Button";

/**
 * Right-hand Session History & Management Sidebar.
 */
export default function SessionSidebar({
  isOpen,
  onClose,
  sessions,
  activeSessionId,
  onSelectSession,
  onNewSession,
  onRenameSession,
  onDeleteSession,
  onClearAllSessions,
}) {
  const [searchQuery, setSearchQuery] = useState("");
  const [renamingSession, setRenamingSession] = useState(null);
  const [deletingSession, setDeletingSession] = useState(null);
  const [isClearAllOpen, setIsClearAllOpen] = useState(false);

  // Filtered session list based on search query
  const filteredSessions = useMemo(() => {
    if (!searchQuery.trim()) return sessions;
    const q = searchQuery.toLowerCase().trim();
    return sessions.filter((s) => {
      const matchTitle = (s.title || "").toLowerCase().includes(q);
      const matchCase = (s.patientCase || "").toLowerCase().includes(q);
      const matchTrials = (s.data?.matches || []).some(
        (m) =>
          (m.nct_id || "").toLowerCase().includes(q) ||
          (m.title || "").toLowerCase().includes(q)
      );
      return matchTitle || matchCase || matchTrials;
    });
  }, [sessions, searchQuery]);

  return (
    <>
      {/* Mobile Backdrop when sidebar is open as a drawer */}
      {isOpen && (
        <div
          className="sidebar-backdrop"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside
        className={`session-sidebar ${isOpen ? "sidebar-open" : "sidebar-closed"}`}
        aria-label="Session history"
      >
        <div className="sidebar-header">
          <div className="sidebar-header-left">
            <span className="sidebar-title">My Sessions</span>
            <span className="sidebar-count">{sessions.length}</span>
          </div>

          <div className="sidebar-header-actions">
            <Button
              variant="outline"
              size="xs"
              onClick={() => onNewSession()}
              title="Start a new patient match session"
              icon="+"
            >
              New
            </Button>
            <button
              type="button"
              className="sidebar-close-btn"
              onClick={onClose}
              title="Close sidebar"
              aria-label="Close sidebar"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Search input if multiple sessions exist */}
        {sessions.length > 1 && (
          <div className="sidebar-search">
            <span className="search-icon">🔍</span>
            <input
              type="text"
              className="sidebar-search-input"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Filter by diagnosis, case or NCT..."
              aria-label="Filter sessions"
            />
            {searchQuery && (
              <button
                type="button"
                className="search-clear-btn"
                onClick={() => setSearchQuery("")}
                title="Clear filter"
              >
                ✕
              </button>
            )}
          </div>
        )}

        {/* Sessions scrollable list */}
        <div className="sidebar-list">
          {filteredSessions.length === 0 ? (
            <div className="sidebar-empty">
              {searchQuery ? (
                <>
                  <p className="sidebar-empty-title">No matching sessions</p>
                  <p className="sidebar-empty-text">
                    No session matches "{searchQuery}".
                  </p>
                  <Button
                    variant="ghost"
                    size="xs"
                    onClick={() => setSearchQuery("")}
                  >
                    Clear filter
                  </Button>
                </>
              ) : (
                <>
                  <div className="sidebar-empty-icon">📁</div>
                  <p className="sidebar-empty-title">No saved sessions</p>
                  <p className="sidebar-empty-text">
                    Your saved sessions and trial evaluations will appear here.
                  </p>
                </>
              )}
            </div>
          ) : (
            filteredSessions.map((session) => (
              <SessionItem
                key={session.id}
                session={session}
                isActive={session.id === activeSessionId}
                onSelect={(id) => {
                  onSelectSession(id);
                  if (window.innerWidth < 1024) {
                    onClose();
                  }
                }}
                onRename={(s) => setRenamingSession(s)}
                onDelete={(s) => setDeletingSession(s)}
              />
            ))
          )}
        </div>

        {/* Footer controls and account-scoped storage note */}
        <div className="sidebar-footer">
          <div className="sidebar-footer-info">
            <span className="info-icon">ⓘ</span>
            <span>Search queries, trial assessments, and chat are saved to your account. Delete a session to remove it.</span>
          </div>

          {sessions.length > 1 && (
            <button
              type="button"
              className="clear-all-btn"
              onClick={() => setIsClearAllOpen(true)}
            >
              Clear all sessions ({sessions.length})
            </button>
          )}
        </div>
      </aside>

      {/* Rename Modal */}
      {renamingSession && (
        <RenameModal
          isOpen={true}
          currentTitle={renamingSession.title}
          onClose={() => setRenamingSession(null)}
          onSave={(newTitle) => onRenameSession(renamingSession.id, newTitle)}
        />
      )}

      {/* Delete Single Session Dialog */}
      {deletingSession && (
        <ConfirmDialog
          isOpen={true}
          title="Delete Session"
          message={`Are you sure you want to delete "${deletingSession.title}"? Any matched trial data and Q&A in this session will be removed.`}
          confirmText="Delete Session"
          confirmVariant="danger"
          onClose={() => setDeletingSession(null)}
          onConfirm={() => {
            onDeleteSession(deletingSession.id);
            setDeletingSession(null);
          }}
        />
      )}

      {/* Clear All Sessions Dialog */}
      {isClearAllOpen && (
        <ConfirmDialog
          isOpen={true}
          title="Clear All Sessions"
          message="Are you sure you want to remove all saved sessions from your account? This will delete their trial assessments and chat history."
          confirmText="Clear All"
          confirmVariant="danger"
          onClose={() => setIsClearAllOpen(false)}
          onConfirm={() => {
            onClearAllSessions();
            setIsClearAllOpen(false);
          }}
        />
      )}
    </>
  );
}

