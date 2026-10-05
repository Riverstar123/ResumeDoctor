import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { api, isMock } from './api';
import { ApiError } from './api/client';
import type { Model, Schema } from './types';

type Workspace = {
  session?: Schema['Session'];
  profileId?: string;
  jobIds: string[];
  selectedJobIds: string[];
  diagnosisIds: string[];
};
const empty = (): Workspace => ({ jobIds: [], selectedJobIds: [], diagnosisIds: [] });
const key = `rd:workspace:${isMock ? 'mock' : 'http'}`;
function read(): Workspace {
  try {
    return { ...empty(), ...JSON.parse(sessionStorage.getItem(key) || '{}') };
  } catch {
    return empty();
  }
}
type Context = {
  workspace: Workspace;
  patch: (patch: Partial<Workspace>) => void;
  models: Model[];
  modelId: string;
  setModelId: (id: string) => void;
  ready: boolean;
  loading: boolean;
  error: unknown;
  start: () => Promise<void>;
  reload: () => void;
  remove: () => Promise<void>;
};
const AppContext = createContext<Context | null>(null);
export function AppProvider({ children }: { children: ReactNode }) {
  const [workspace, setWorkspace] = useState(read);
  const [models, setModels] = useState<Model[]>([]);
  const [modelId, setModelId] = useState('');
  const [ready, setReady] = useState(false);
  const [loading, setLoading] = useState(Boolean(workspace.session));
  const [error, setError] = useState<unknown>();
  const [revision, setRevision] = useState(0);
  const patch = (change: Partial<Workspace>) => setWorkspace((w) => ({ ...w, ...change }));
  useEffect(() => {
    sessionStorage.setItem(key, JSON.stringify(workspace));
  }, [workspace]);
  useEffect(() => {
    const expired = () => {
      setReady(false);
      setWorkspace(empty());
      setModels([]);
      setError(
        new ApiError(
          401,
          'SESSION_EXPIRED',
          '会话已过期。请重新确认后开始，旧会话资料不可继续访问。',
        ),
      );
    };
    window.addEventListener('rd:session-expired', expired);
    return () => window.removeEventListener('rd:session-expired', expired);
  }, []);
  useEffect(() => {
    if (!workspace.session) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(undefined);
    api
      .models(controller.signal)
      .then((list) => {
        if (controller.signal.aborted) return;
        setModels(list.items);
        setModelId((current) => current || list.default_model_id);
        setReady(true);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(err);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [workspace.session?.id, revision]);
  const start = async () => {
    setLoading(true);
    setError(undefined);
    try {
      const session = await api.session();
      patch({ session });
      setRevision((v) => v + 1);
    } catch (err) {
      setError(err);
      setLoading(false);
    }
  };
  const remove = async () => {
    await api.deleteSession();
    setWorkspace(empty());
    setReady(false);
    setModels([]);
    setModelId('');
    setError(undefined);
  };
  return (
    <AppContext.Provider
      value={{
        workspace,
        patch,
        models,
        modelId,
        setModelId,
        ready,
        loading,
        error,
        start,
        remove,
        reload: () => setRevision((n) => n + 1),
      }}
    >
      {children}
    </AppContext.Provider>
  );
}
export function useApp() {
  const value = useContext(AppContext);
  if (!value) throw new Error('AppProvider required');
  return value;
}
