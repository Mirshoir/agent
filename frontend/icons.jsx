/* global window */
import React from 'react';
// Hand-curated, simple, consistent stroke icons (Lucide-style minimal)
const ICON_PROPS = { viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round' };

const I = {
  Inbox: (p) => (<svg width="18" height="18" {...ICON_PROPS} {...p}><path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11Z"/></svg>),
  Comment:(p) => (<svg width="18" height="18" {...ICON_PROPS} {...p}><path d="M21 15a2 2 0 0 1-2 2H8l-5 5V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>),
  Chart: (p) => (<svg width="18" height="18" {...ICON_PROPS} {...p}><path d="M3 3v18h18"/><path d="M7 14l4-4 4 4 5-7"/></svg>),
  Book:  (p) => (<svg width="18" height="18" {...ICON_PROPS} {...p}><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/></svg>),
  Layers:(p) => (<svg width="18" height="18" {...ICON_PROPS} {...p}><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>),
  Sett:  (p) => (<svg width="18" height="18" {...ICON_PROPS} {...p}><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9c.36.16.65.43.85.78.2.36.31.76.31 1.18V11a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.5 1Z"/></svg>),
  Search:(p) => (<svg width="14" height="14" {...ICON_PROPS} {...p}><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>),
  Send:  (p) => (<svg width="14" height="14" {...ICON_PROPS} {...p}><path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4 20-7Z"/></svg>),
  Photo: (p) => (<svg width="16" height="16" {...ICON_PROPS} {...p}><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5L5 21"/></svg>),
  Mic:   (p) => (<svg width="16" height="16" {...ICON_PROPS} {...p}><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><path d="M12 19v3"/></svg>),
  Smile: (p) => (<svg width="16" height="16" {...ICON_PROPS} {...p}><circle cx="12" cy="12" r="9"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>),
  Paperclip:(p) => (<svg width="16" height="16" {...ICON_PROPS} {...p}><path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 17.99 8.84l-8.57 8.57a2 2 0 0 1-2.83-2.83l8.06-8.06"/></svg>),
  Sparkle:(p) => (<svg width="14" height="14" {...ICON_PROPS} {...p}><path d="M9.94 14.34 12 22l2.06-7.66L22 12l-7.94-2.34L12 2l-2.06 7.66L2 12Z"/></svg>),
  Dots:  (p) => (<svg width="16" height="16" {...ICON_PROPS} {...p}><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></svg>),
  Phone: (p) => (<svg width="16" height="16" {...ICON_PROPS} {...p}><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92Z"/></svg>),
  Info:  (p) => (<svg width="16" height="16" {...ICON_PROPS} {...p}><circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/></svg>),
  Pin:   (p) => (<svg width="14" height="14" {...ICON_PROPS} {...p}><path d="M12 2v6"/><path d="m9 11 3 3 3-3"/><path d="M12 14v8"/></svg>),
  Archive:(p) => (<svg width="16" height="16" {...ICON_PROPS} {...p}><rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/></svg>),
  Star:  (p) => (<svg width="14" height="14" {...ICON_PROPS} {...p}><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>),
  Sun:   (p) => (<svg width="14" height="14" {...ICON_PROPS} {...p}><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>),
  Moon:  (p) => (<svg width="14" height="14" {...ICON_PROPS} {...p}><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z"/></svg>),
  Inst:  (p) => (<svg width="10" height="10" {...ICON_PROPS} strokeWidth="2" {...p}><rect x="2" y="2" width="20" height="20" rx="5"/><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37Z"/><path d="M17.5 6.5h.01"/></svg>),
  Tg:    (p) => (<svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor" {...p}><path d="M9.78 18.65l.28-4.23 7.68-6.92c.34-.31-.07-.46-.52-.19L7.74 13.3 3.64 12c-.88-.25-.89-.86.2-1.3l15.97-6.16c.73-.33 1.43.18 1.15 1.3l-2.72 12.81c-.19.91-.74 1.13-1.5.71L12.6 16.3l-1.99 1.93c-.23.23-.42.42-.83.42z"/></svg>),
  Wa:    (p) => (<svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor" {...p}><path d="M17.6 6.32A7.85 7.85 0 0 0 12.05 4a7.94 7.94 0 0 0-6.88 11.9L4 20l4.22-1.11a7.93 7.93 0 0 0 3.82.97h.01c4.38 0 7.94-3.56 7.94-7.94a7.88 7.88 0 0 0-2.39-5.6Zm-5.55 12.21h-.01a6.6 6.6 0 0 1-3.36-.92l-.24-.14-2.5.66.67-2.44-.16-.25a6.6 6.6 0 1 1 5.6 3.09Zm3.62-4.94c-.2-.1-1.17-.58-1.35-.65-.18-.07-.31-.1-.45.1-.13.2-.51.65-.62.78-.12.13-.23.15-.42.05-.2-.1-.84-.31-1.6-.99-.59-.53-.99-1.18-1.1-1.38-.12-.2-.01-.3.09-.4.09-.09.2-.23.3-.34.1-.12.13-.2.2-.33.06-.13.03-.25-.02-.35-.05-.1-.45-1.08-.62-1.48-.16-.39-.33-.34-.45-.34l-.38-.01a.74.74 0 0 0-.54.25c-.18.2-.7.69-.7 1.67 0 .99.72 1.94.82 2.07.1.13 1.41 2.15 3.42 3.02.48.2.85.33 1.14.42.48.15.92.13 1.26.08.39-.06 1.17-.48 1.34-.94.16-.46.16-.86.12-.94-.05-.08-.18-.13-.38-.23Z"/></svg>),
  Check: (p) => (<svg width="11" height="11" {...ICON_PROPS} strokeWidth="2.2" {...p}><polyline points="20 6 9 17 4 12"/></svg>),
  DoubleCheck: (p) => (<svg width="13" height="11" {...ICON_PROPS} strokeWidth="2" {...p}><polyline points="18 7 11 14"/><polyline points="6 12 2 16"/><polyline points="22 7 11 18 9 16"/></svg>),
  AlertTri:(p) => (<svg width="14" height="14" {...ICON_PROPS} {...p}><path d="m21.73 18-8-14a2 2 0 0 0-3.46 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>),
  Caret: (p) => (<svg width="10" height="10" {...ICON_PROPS} {...p}><polyline points="6 9 12 15 18 9"/></svg>),
  Plus:  (p) => (<svg width="14" height="14" {...ICON_PROPS} {...p}><path d="M12 5v14M5 12h14"/></svg>),
  Bell:  (p) => (<svg width="16" height="16" {...ICON_PROPS} {...p}><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>),
  Heart: (p) => (<svg width="14" height="14" {...ICON_PROPS} {...p}><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/></svg>),
  Logout:(p) => (<svg width="16" height="16" {...ICON_PROPS} {...p}><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>),
};

window.I = I;
