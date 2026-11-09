import { act, fireEvent, render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { parseTheme, THEME_STORAGE_KEY, useTheme } from '../src/theme';

function ThemeControl() {
  const { preference, changeTheme } = useTheme();
  return (
    <select
      aria-label="外观模式"
      value={preference}
      onChange={(e) => changeTheme(parseTheme(e.target.value))}
    >
      <option value="system">跟随系统</option>
      <option value="light">浅色</option>
      <option value="dark">深色</option>
    </select>
  );
}

let systemDark = false;
let listeners: Set<() => void>;
function changeSystem(dark: boolean) {
  act(() => {
    systemDark = dark;
    listeners.forEach((listener) => listener());
  });
}
beforeEach(() => {
  localStorage.clear();
  systemDark = false;
  listeners = new Set();
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => ({
      get matches() {
        return systemDark;
      },
      addEventListener: (_: string, callback: () => void) => listeners.add(callback),
      removeEventListener: (_: string, callback: () => void) => listeners.delete(callback),
    })),
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  delete document.documentElement.dataset.theme;
  document.documentElement.style.colorScheme = '';
});

describe('theme preferences', () => {
  it('follows system changes only while system is selected and cleans up listeners', () => {
    const { unmount } = render(<ThemeControl />);
    expect(document.documentElement.dataset.theme).toBe('light');
    fireEvent.change(screen.getByLabelText('外观模式'), { target: { value: 'system' } });
    changeSystem(true);
    expect(document.documentElement.dataset.theme).toBe('dark');
    fireEvent.change(screen.getByLabelText('外观模式'), { target: { value: 'light' } });
    changeSystem(false);
    changeSystem(true);
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(document.documentElement.style.colorScheme).toBe('light');
    fireEvent.change(screen.getByLabelText('外观模式'), { target: { value: 'system' } });
    expect(document.documentElement.dataset.theme).toBe('dark');
    unmount();
    expect(listeners.size).toBe(0);
  });

  it('remembers an explicit choice across remounts and accepts changes from another tab', () => {
    const { unmount } = render(<ThemeControl />);
    fireEvent.change(screen.getByLabelText('外观模式'), { target: { value: 'dark' } });
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
    unmount();
    render(<ThemeControl />);
    expect(screen.getByLabelText('外观模式')).toHaveValue('dark');
    act(() => {
      localStorage.setItem(THEME_STORAGE_KEY, 'light');
      window.dispatchEvent(new StorageEvent('storage', { key: THEME_STORAGE_KEY }));
    });
    expect(document.documentElement.dataset.theme).toBe('light');
  });

  it('still switches themes if browser storage is denied', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied');
    });
    render(<ThemeControl />);
    fireEvent.change(screen.getByLabelText('外观模式'), { target: { value: 'dark' } });
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('boots safely when storage and system-theme detection are unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied');
    });
    vi.stubGlobal('matchMedia', undefined);
    const html = readFileSync('index.html', 'utf8');
    const bootstrap = html.match(/<script>([\s\S]*?)<\/script>/)![1];
    const meta = document.createElement('meta');
    meta.name = 'theme-color';
    document.head.append(meta);
    try {
      expect(() => new Function(bootstrap)()).not.toThrow();
      expect(document.documentElement.dataset.theme).toBe('light');
      render(<ThemeControl />);
      fireEvent.change(screen.getByLabelText('外观模式'), { target: { value: 'dark' } });
      expect(document.documentElement.dataset.theme).toBe('dark');
    } finally {
      meta.remove();
    }
  });

  it.each(['dark', 'light', 'invalid', null])(
    'resolves saved preference %s before the app loads',
    (saved) => {
      systemDark = true;
      if (saved) localStorage.setItem(THEME_STORAGE_KEY, saved);
      const html = readFileSync('index.html', 'utf8');
      const bootstrap = html.match(/<script>([\s\S]*?)<\/script>/)![1];
      const meta = document.createElement('meta');
      meta.name = 'theme-color';
      document.head.append(meta);
      try {
        expect(html.indexOf(bootstrap)).toBeLessThan(html.indexOf('/src/main.tsx'));
        new Function(bootstrap)();
        const expected = saved === 'light' ? 'light' : 'dark';
        expect(document.documentElement.dataset.theme).toBe(expected);
        expect(document.documentElement.style.colorScheme).toBe(expected);
        expect(meta.content).toBe(expected === 'dark' ? '#07080f' : '#f7f7fb');
      } finally {
        meta.remove();
      }
    },
  );
});
