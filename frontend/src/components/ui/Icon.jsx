import React from "react";

const PATHS = {
  search: <><circle cx="10.8" cy="10.8" r="6.8" /><path d="m16 16 4.2 4.2M8 10.8h5.6M10.8 8v5.6" /></>,
  clipboard: <><rect x="6" y="4.5" width="12" height="16" rx="2" /><path d="M9 4.5v-1h6v1M9 10h6M9 14h6M9 17.5h4" /></>,
  folder: <path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H10l2 2h6.5A2.5 2.5 0 0 1 21 9.5v7a2.5 2.5 0 0 1-2.5 2.5h-13A2.5 2.5 0 0 1 3 16.5v-9Z" />,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></>,
  person: <><circle cx="12" cy="8" r="3.5" /><path d="M5.5 20a6.5 6.5 0 0 1 13 0" /></>,
  edit: <><path d="m14 5 5 5M4 20l4.2-.9L19 8.3a2.1 2.1 0 0 0-3-3L5.2 16.1 4 20Z" /></>,
  trash: <><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5" /></>,
  chat: <><path d="M20 11.5a7.5 7.5 0 0 1-8 7.5 8.6 8.6 0 0 1-3.5-.7L4 20l1.3-3.5A7.1 7.1 0 0 1 4 12c0-4.1 3.6-7.5 8-7.5s8 3.1 8 7Z" /><path d="M8 11h8M8 14h5" /></>,
  sparkle: <><path d="m12 3 1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9L12 3ZM19 16l1 2.5 2.5 1-2.5 1-1 2.5-1-2.5-2.5-1 2.5-1 1-2.5Z" /></>,
  arrow: <><path d="M4 12h15M13 6l6 6-6 6" /></>,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  logout: <><path d="M10 4H5.5A1.5 1.5 0 0 0 4 5.5v13A1.5 1.5 0 0 0 5.5 20H10" /><path d="M13 8l4 4-4 4M17 12H9" /></>,
  shield: <><path d="M12 3 20 6v5.5c0 5-3.3 8.4-8 10.5-4.7-2.1-8-5.5-8-10.5V6l8-3Z" /><path d="M12 8v8M8 12h8" /></>,
  dna: <><path d="M7 3c0 8 10 10 10 18M17 3c0 8-10 10-10 18M8 7h8M7 12h10M8 17h8" /></>,
};

/** Small shared line icon for the clinical workspace. */
export default function Icon({ name, size = 18, className = "" }) {
  return <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">{PATHS[name] || PATHS.info}</svg>;
}
