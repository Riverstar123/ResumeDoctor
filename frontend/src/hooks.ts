import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import { ApiError, pollTask } from './api/client';
import type { Task } from './types';

export function useLoad<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  key: string,
  { keepPreviousData = false }: { keepPreviousData?: boolean } = {},
) {
  const [state, setState] = useState<{ data?: T; error?: unknown; loading: boolean }>({
    loading: true,
  });
  const [revision, setRevision] = useState(0);
  const fn = useRef(loader);
  fn.current = loader;
  useEffect(() => {
    const controller = new AbortController();
    // Opt-in: keep the current data while reloading so a list refresh does not
    // unmount the editor that depends on it (unsaved drafts would be lost).
    // The default stays a hard reset, which callers that remount on data changes rely on.
    setState((previous) =>
      keepPreviousData ? { ...previous, error: undefined, loading: true } : { loading: true },
    );
    fn.current(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ data, loading: false });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setState({ error, loading: false });
      });
    return () => controller.abort();
  }, [key, revision, keepPreviousData]);
  return { ...state, reload: () => setRevision((n) => n + 1) };
}

export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [retryAt, setRetryAt] = useState(0);
  const [now, setNow] = useState(Date.now());
  const lock = useRef(false);
  const operation = useRef<{ signature: string; key: string; payload?: { value: unknown } }>({
    signature: '',
    key: '',
  });
  useEffect(() => {
    if (retryAt <= Date.now()) return;
    const timer = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(timer);
  }, [retryAt]);
  const run = async <T, P = undefined>(
    fn: (key: string, payload: P) => Promise<T>,
    signature = 'default',
    prepare?: (key: string) => Promise<P> | P,
  ): Promise<T | undefined> => {
    if (lock.current || retryAt > Date.now()) return;
    lock.current = true;
    setBusy(true);
    setError(undefined);
    try {
      // A retry keeps the idempotency key, so it must also replay the exact same
      // request body. `prepare` therefore runs once per key and is frozen until
      // the operation ends; only a new operation reads fresh state and gets a new key.
      if (operation.current.signature !== signature || !operation.current.key)
        operation.current = { signature, key: crypto.randomUUID() };
      const current = operation.current;
      if (!current.payload && prepare) current.payload = { value: await prepare(current.key) };
      const value = await fn(current.key, current.payload?.value as P);
      operation.current = { signature: '', key: '' };
      return value;
    } catch (err) {
      setError(err);
      if (err instanceof ApiError && err.status === 429)
        setRetryAt(Date.now() + Math.max(1, err.retryAfter) * 1000);
      return undefined;
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };
  return {
    busy,
    error,
    run,
    setError,
    clearError: () => setError(undefined),
    cooldown: Math.max(0, Math.ceil((retryAt - now) / 1000)),
  };
}

export function useTask(id: string | null) {
  const [task, setTask] = useState<Task>();
  const [error, setError] = useState<unknown>();
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    setTask(undefined);
    setError(undefined);
    if (!id) return;
    const controller = new AbortController();
    void pollTask(api, id, setTask, controller.signal).catch((err) => {
      if (!controller.signal.aborted) setError(err);
    });
    return () => controller.abort();
  }, [id, revision]);
  return { task, error, retry: () => setRevision((n) => n + 1) };
}
