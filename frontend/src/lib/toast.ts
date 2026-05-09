/**
 * Minimal toast notification system.
 * No external deps — uses a simple event bus + a React hook.
 */

export type ToastType = "success" | "error" | "info" | "warning";

export interface ToastAction {
  label: string;
  onClick: () => void | Promise<void>;
  variant?: "primary" | "secondary";
  dismissOnClick?: boolean;
}

export interface Toast {
  id: string;
  type: ToastType;
  message: string;
  duration: number;
  actions?: ToastAction[];
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
  duration = 3500,
  actions?: ToastAction[]
) {
  const t: Toast = {
    id: `toast-${++counter}`,
    type,
    message,
    duration,
    actions,
  };
  for (const fn of listeners) fn(t);
}
