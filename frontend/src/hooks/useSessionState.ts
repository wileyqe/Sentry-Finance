import { useState, useCallback } from "react";

const DEFAULT_TTL_MS = 15 * 60 * 1000; // 15 minutes
const KEY_PREFIX = "sentry:session:";

interface StorageEnvelope<T> {
  v: T;
  ts: number;
}

function readFromStorage<T>(fullKey: string, defaultValue: T, ttlMs: number): T {
  try {
    const raw = sessionStorage.getItem(fullKey);
    if (raw === null) return defaultValue;
    const envelope: StorageEnvelope<T> = JSON.parse(raw);
    if (!envelope || typeof envelope.ts !== "number") {
      sessionStorage.removeItem(fullKey);
      return defaultValue;
    }
    if (Date.now() - envelope.ts > ttlMs) {
      sessionStorage.removeItem(fullKey);
      return defaultValue;
    }
    return envelope.v;
  } catch {
    sessionStorage.removeItem(fullKey);
    return defaultValue;
  }
}

function writeToStorage<T>(fullKey: string, value: T): void {
  try {
    sessionStorage.setItem(fullKey, JSON.stringify({ v: value, ts: Date.now() }));
  } catch {
    // sessionStorage full or unavailable — silently degrade
  }
}

export function useSessionState<T>(
  key: string,
  defaultValue: T,
  options?: { ttlMs?: number },
): [T, React.Dispatch<React.SetStateAction<T>>] {
  const ttlMs = options?.ttlMs ?? DEFAULT_TTL_MS;
  const fullKey = KEY_PREFIX + key;

  const [value, setValueInternal] = useState<T>(() =>
    readFromStorage(fullKey, defaultValue, ttlMs),
  );

  const setValue: React.Dispatch<React.SetStateAction<T>> = useCallback(
    (action) => {
      setValueInternal((prev) => {
        const next =
          typeof action === "function"
            ? (action as (prev: T) => T)(prev)
            : action;
        writeToStorage(fullKey, next);
        return next;
      });
    },
    [fullKey],
  );

  return [value, setValue];
}

export function clearSessionState(keyPrefix?: string): void {
  const prefix = KEY_PREFIX + (keyPrefix ?? "");
  const toRemove: string[] = [];
  for (let i = 0; i < sessionStorage.length; i++) {
    const k = sessionStorage.key(i);
    if (k && k.startsWith(prefix)) {
      toRemove.push(k);
    }
  }
  toRemove.forEach((k) => sessionStorage.removeItem(k));
}
