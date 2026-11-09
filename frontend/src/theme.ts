import { useLayoutEffect, useState } from 'react';

export type ThemePreference = 'system' | 'light' | 'dark';
export const THEME_STORAGE_KEY = 'rd:theme';
const DARK_QUERY = '(prefers-color-scheme: dark)';

export function parseTheme(value: string | null): ThemePreference {
  return value === 'light' || value === 'dark' ? value : 'system';
}

function readPreference(): ThemePreference {
  try {
    const saved = localStorage.getItem(THEME_STORAGE_KEY);
    return saved ? parseTheme(saved) : 'light';
  } catch {
    return 'light';
  }
}

export function useTheme() {
  const [preference, setPreference] = useState<ThemePreference>(readPreference);

  useLayoutEffect(() => {
    const media = window.matchMedia?.(DARK_QUERY);
    const apply = () => {
      const dark = preference === 'dark' || (preference === 'system' && media?.matches);
      const theme = dark ? 'dark' : 'light';
      document.documentElement.dataset.theme = theme;
      document.documentElement.style.colorScheme = theme;
      document
        .querySelector('meta[name="theme-color"]')
        ?.setAttribute('content', dark ? '#07080f' : '#f7f7fb');
    };
    apply();
    media?.addEventListener('change', apply);
    const onStorage = (event: StorageEvent) => {
      if (event.key === THEME_STORAGE_KEY || event.key === null) {
        setPreference(readPreference());
      }
    };
    window.addEventListener('storage', onStorage);
    return () => {
      media?.removeEventListener('change', apply);
      window.removeEventListener('storage', onStorage);
    };
  }, [preference]);

  const changeTheme = (next: ThemePreference) => {
    setPreference(next);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // Private browsing may deny storage; the current tab can still switch themes.
    }
  };
  return { preference, changeTheme };
}
