type PersistEnvelope<T> = {
  version: number;
  expiresAt: number;
  state: T;
};

export const PAGE_STATE_STORAGE_KEYS = [
  'dsa-analysis-store',
  'dsa-screener-store',
  'dsa-monitor-store',
] as const;

export const PAGE_STATE_STORAGE_LABELS: Record<(typeof PAGE_STATE_STORAGE_KEYS)[number], string> = {
  'dsa-analysis-store': '首页分析',
  'dsa-screener-store': '选股页',
  'dsa-monitor-store': '看盘页',
};

export function createVersionedSessionStorage<T>(version: number, ttlMs: number) {
  return {
    getItem: (key: string) => {
      const raw = sessionStorage.getItem(key);
      if (!raw) return null;

      try {
        const parsed = JSON.parse(raw) as PersistEnvelope<T>;
        if (!parsed || typeof parsed !== 'object') {
          sessionStorage.removeItem(key);
          return null;
        }
        if (parsed.version !== version) {
          sessionStorage.removeItem(key);
          return null;
        }
        if (typeof parsed.expiresAt !== 'number' || Date.now() > parsed.expiresAt) {
          sessionStorage.removeItem(key);
          return null;
        }
        return JSON.stringify(parsed.state);
      } catch {
        sessionStorage.removeItem(key);
        return null;
      }
    },
    setItem: (key: string, value: string) => {
      try {
        const state = JSON.parse(value) as T;
        const envelope: PersistEnvelope<T> = {
          version,
          expiresAt: Date.now() + ttlMs,
          state,
        };
        sessionStorage.setItem(key, JSON.stringify(envelope));
      } catch {
        sessionStorage.removeItem(key);
      }
    },
    removeItem: (key: string) => {
      sessionStorage.removeItem(key);
    },
  };
}

export const SESSION_PERSIST_TTL_MS = 6 * 60 * 60 * 1000;

export function clearPageStateCache(): void {
  for (const key of PAGE_STATE_STORAGE_KEYS) {
    sessionStorage.removeItem(key);
  }
}

export function clearPageStateCacheByKey(key: (typeof PAGE_STATE_STORAGE_KEYS)[number]): void {
  sessionStorage.removeItem(key);
}
