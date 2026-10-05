import { useEffect, useRef, useState } from 'react';
import { api } from './api';
import { ApiError, pollTask } from './api/client';
import type { Task } from './types';

export function useLoad<T>(loader: (signal: AbortSignal) => Promise<T>, key: string) {
  const [state, setState] = useState<{ data?: T; error?: unknown; loading: boolean }>({
    loading: true,
  });
  const [revision, setRevision] = useState(0);
  const fn = useRef(loader);
  fn.current = loader;
  useEffect(() => {
    const controller = new AbortController();
    setState({ loading: true });
    fn.current(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setState({ data, loading: false });
      })
      .catch((error) => {
        if (!controller.signal.aborted) setState({ error, loading: false });
      });
    return () => controller.abort();
  }, [key, revision]);
  return { ...state, reload: () => setRevision((n) => n + 1) };
}

export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [retryAt, setRetryAt] = useState(0);
  const [now, setNow] = useState(Date.now());
  const lock = useRef(false);
  const operation = useRef({ signature: '', key: '' });
  useEffect(() => {
    if (retryAt <= Date.now()) return;
    const timer = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(timer);
  }, [retryAt]);
  const run = async <T>(
    fn: (key: string) => Promise<T>,
    signature = 'default',
  ): Promise<T | undefined> => {
    if (lock.current || retryAt > Date.now()) return;
    if (operation.current.signature !== signature || !operation.current.key)
      operation.current = { signature, key: crypto.randomUUID() };
    lock.current = true;
    setBusy(true);
    setError(undefined);
    try {
      const value = await fn(operation.current.key);
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
