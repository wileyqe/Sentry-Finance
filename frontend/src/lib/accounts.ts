/**
 * Shared account & category data context.
 *
 * Replaces the hardcoded ACCOUNT_NAMES map duplicated across 5+ pages
 * with a single API-driven lookup fetched once and shared via React context.
 */

import { createContext, useContext } from "react";

export interface AccountInfo {
  id: string;
  name: string;
  institution_id: string;
  type: string;
  last4: string;
}

export interface AccountsContextValue {
  accounts: AccountInfo[];
  accountNames: Record<string, string>;
  categories: string[];
  loading: boolean;
}

export const AccountsContext = createContext<AccountsContextValue>({
  accounts: [],
  accountNames: {},
  categories: [],
  loading: true,
});

export function useAccounts() {
  return useContext(AccountsContext);
}

/**
 * Build an account ID → display name map from the API response.
 * Falls back to the raw account_id if name is missing.
 */
export function buildAccountNames(accounts: AccountInfo[]): Record<string, string> {
  const map: Record<string, string> = {};
  for (const a of accounts) {
    map[a.id] = a.name || a.id;
  }
  return map;
}
