import type { ReactNode } from 'react';

// Small hand-drawn stroke icons for the shell and landing page. They are purely
// decorative (aria-hidden); every control that uses one keeps a text label.
// Do not use them inside report content: the report page keeps #main-content
// free of <svg> so injected markup is easy to detect.
function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

export function IconLogo() {
  return (
    <Icon>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5" />
      <path d="M8 14.5h2l1.4-3 2.2 6 1.4-3H16" />
    </Icon>
  );
}

export function IconSystem() {
  return (
    <Icon>
      <rect x="3" y="4" width="18" height="12.5" rx="2.2" />
      <path d="M8.5 20.5h7M12 16.5v4" />
    </Icon>
  );
}

export function IconSun() {
  return (
    <Icon>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4" />
    </Icon>
  );
}

export function IconMoon() {
  return (
    <Icon>
      <path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5Z" />
    </Icon>
  );
}

export function IconTrash() {
  return (
    <Icon>
      <path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l.8 12.2a1.6 1.6 0 0 0 1.6 1.5h6.2a1.6 1.6 0 0 0 1.6-1.5L17.5 7M10 11v6M14 11v6" />
    </Icon>
  );
}

export function IconSpark() {
  return (
    <Icon>
      <path d="M12 3.5 13.9 8.6 19 10.5 13.9 12.4 12 17.5 10.1 12.4 5 10.5 10.1 8.6Z" />
      <path d="M19 15.5 19.7 17.3 21.5 18 19.7 18.7 19 20.5 18.3 18.7 16.5 18 18.3 17.3Z" />
    </Icon>
  );
}

export function IconCheck() {
  return (
    <Icon>
      <path d="m5 12.5 4.2 4.2L19 7" />
    </Icon>
  );
}

export function IconScale() {
  return (
    <Icon>
      <path d="M12 4v16M7.5 20h9M5 7h14" />
      <path d="M5 7 2.5 13a2.6 2.6 0 0 0 5 0Z" />
      <path d="m19 7-2.5 6a2.6 2.6 0 0 0 5 0Z" />
    </Icon>
  );
}

export function IconShield() {
  return (
    <Icon>
      <path d="M12 3 4.5 6v5.5c0 4.6 3.1 8.2 7.5 9.5 4.4-1.3 7.5-4.9 7.5-9.5V6Z" />
      <path d="m8.8 12.2 2.3 2.3 4.3-4.6" />
    </Icon>
  );
}
