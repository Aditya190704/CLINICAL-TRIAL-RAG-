import React from "react";

/**
 * AppShell: Coherent Single-Window layout combining Header, Main Workspace, and Sidebar.
 */
export default function AppShell({
  header,
  children,
  sidebar,
  isSidebarOpen,
  footer,
}) {
  return (
    <div className={`app-shell ${isSidebarOpen ? "with-sidebar-open" : "with-sidebar-closed"}`}>
      {header}

      <div className="workspace-container">
        <main className="main-workspace" id="main-content">
          <div className="workspace-content">{children}</div>
        </main>

        {sidebar}
      </div>

      {footer}
    </div>
  );
}

