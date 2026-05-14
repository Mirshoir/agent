/* global React, window */

window.I = {
  Inbox: () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M5 4h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z" />
      <polyline points="2 7 12 13 22 7" />
    </svg>
  ),

  Chart: () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="12" y1="2" x2="12" y2="22" />
      <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
    </svg>
  ),

  Book: () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 -2.5-2.5z" />
      <polyline points="10 6 10 18" />
    </svg>
  ),

  Layers: () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polygon points="12 2 2 7 2 17 12 22 22 17 22 7 12 2" />
      <polyline points="2 7 12 12 22 7" />
      <polyline points="2 17 12 12 22 17" />
    </svg>
  ),

  Sett: () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 1v6m0 6v6M4.22 4.22l4.24 4.24m5.08 0l4.24-4.24M1 12h6m6 0h6M4.22 19.78l4.24-4.24m5.08 0l4.24 4.24M19 1v6m0 6v6" />
    </svg>
  ),

  Search: () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.35-4.35" />
    </svg>
  ),

  Inst: () => (
    <svg viewBox="0 0 24 24" fill="currentColor">
      <rect x="2" y="2" width="20" height="20" rx="5" ry="5" fill="none" stroke="currentColor" strokeWidth="2" />
      <rect x="6" y="6" width="12" height="12" rx="3" ry="3" fill="none" stroke="currentColor" strokeWidth="2" />
      <circle cx="12" cy="12" r="2" fill="currentColor" />
      <circle cx="17.5" cy="6.5" r="1.5" fill="currentColor" />
    </svg>
  ),

  Tg: () => (
    <svg viewBox="0 0 24 24" fill="currentColor">
      <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="2" />
      <path d="M8 12l3 3 5-6" stroke="currentColor" strokeWidth="2" fill="none" />
    </svg>
  ),

  Wa: () => (
    <svg viewBox="0 0 24 24" fill="currentColor">
      <path d="M17.6 6.4c-1.2-1.2-2.8-1.9-4.6-1.9-3.6 0-6.5 2.9-6.5 6.5 0 1.1.3 2.2.8 3.1L6 18l3.9-1.3c.9.5 2 .8 3.1.8 3.6 0 6.5-2.9 6.5-6.5 0-1.8-.7-3.4-1.9-4.6z" stroke="currentColor" strokeWidth="2" fill="none" />
    </svg>
  ),

  Sparkle: () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
    </svg>
  ),

  Dots: () => (
    <svg viewBox="0 0 24 24" fill="currentColor">
      <circle cx="12" cy="5" r="2" />
      <circle cx="12" cy="12" r="2" />
      <circle cx="12" cy="19" r="2" />
    </svg>
  ),

  Send: () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <line x1="22" y1="2" x2="11" y2="13" />
      <polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  ),

  Paperclip: () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21.5 2v19a2 2 0 0 1-2 2H4.5a2 2 0 0 1-2-2V2" />
      <path d="M3.5 5h17M3.5 10h17M3.5 15h17" />
    </svg>
  ),

  Photo: () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
      <circle cx="8.5" cy="8.5" r="1.5" />
      <polyline points="21 15 16 10 5 21" />
    </svg>
  ),

  Mic: () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 1a3 3 0 0 0-3 3v12a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  ),

  Smile: () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" />
      <path d="M8 14s1.5 2 4 2 4-2 4-2" />
      <line x1="9" y1="9" x2="9.01" y2="9" />
      <line x1="15" y1="9" x2="15.01" y2="9" />
    </svg>
  ),

  Bell: () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 0 1-3.46 0" />
    </svg>
  ),

  Sun: () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="5" />
      <line x1="12" y1="1" x2="12" y2="3" />
      <line x1="12" y1="21" x2="12" y2="23" />
      <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
      <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
      <line x1="1" y1="12" x2="3" y2="12" />
      <line x1="21" y1="12" x2="23" y2="12" />
      <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
      <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
    </svg>
  ),

  Moon: () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  ),

  Caret: () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="6 9 12 15 18 9" />
    </svg>
  ),

  AlertTri: () => (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3.05h16.94a2 2 0 0 0 1.71-3.05L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  ),
};
