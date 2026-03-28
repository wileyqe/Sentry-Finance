/**
 * Minimal toast notification system.
 * No external deps — uses a simple event bus + a React hook.
 */

export type ToastType = "success" | "error" | "info";

export interface Toast {
  id: string;
  type: ToastType;
  message: string;
  duration: number;
}

type Listener = (toast: Toast) => void;
const listeners: Listener[] = [];

export function addToastListener(fn: Listener) {
  listeners.push(fn);
  return () => {
    const idx = listeners.indexOf(fn);
    if (idx >= 0) listeners.splice(idx, 1);
  };
}

let counter = 0;

export function toast(
  message: string,
  type: ToastType = "info",
  duration = 3500
) {
  const t: Toast = { id: `toast-${++counter}`, type, message, duration };
  for (const fn of listeners) fn(t);
}
