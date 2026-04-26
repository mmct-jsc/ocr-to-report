import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { Client } from "@ocr-to-report/sdk";

const KEY_STORAGE = "ocr2r:apiKey";
const URL_STORAGE = "ocr2r:baseUrl";
const ACTING_STORAGE = "ocr2r:actingTenantId";
const DEFAULT_BASE_URL = "/api";

interface AuthState {
  apiKey: string | null;
  baseUrl: string;
  client: Client | null;
  /**
   * When non-null, the SDK sends ``X-Acting-Tenant-Id`` so the server
   * scopes tenant-bound endpoints (jobs, transcripts, webhooks, dsr,
   * usage) to that tenant instead of the calling key's home tenant.
   * Requires the key to have ``admin:*``.
   */
  actingTenantId: string | null;
  signIn: (apiKey: string, baseUrl?: string) => void;
  signOut: () => void;
  setActingTenantId: (id: string | null) => void;
}

const AuthContext = createContext<AuthState | null>(null);

function readStored(key: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  return window.localStorage.getItem(key) ?? fallback;
}

function readNullable(key: string): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(key);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [apiKey, setApiKey] = useState<string | null>(() => readNullable(KEY_STORAGE));
  const [baseUrl, setBaseUrl] = useState<string>(() => readStored(URL_STORAGE, DEFAULT_BASE_URL));
  const [actingTenantId, setActingTenantIdState] = useState<string | null>(() =>
    readNullable(ACTING_STORAGE),
  );

  const client = useMemo<Client | null>(() => {
    if (!apiKey) return null;
    return new Client({ baseUrl, apiKey, actingTenantId });
  }, [apiKey, baseUrl, actingTenantId]);

  const value: AuthState = {
    apiKey,
    baseUrl,
    client,
    actingTenantId,
    signIn: (newKey, newBase) => {
      setApiKey(newKey);
      window.localStorage.setItem(KEY_STORAGE, newKey);
      if (newBase) {
        setBaseUrl(newBase);
        window.localStorage.setItem(URL_STORAGE, newBase);
      }
    },
    signOut: () => {
      setApiKey(null);
      setActingTenantIdState(null);
      window.localStorage.removeItem(KEY_STORAGE);
      window.localStorage.removeItem(ACTING_STORAGE);
    },
    setActingTenantId: (id) => {
      setActingTenantIdState(id);
      if (id === null) {
        window.localStorage.removeItem(ACTING_STORAGE);
      } else {
        window.localStorage.setItem(ACTING_STORAGE, id);
      }
    },
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth requires <AuthProvider>");
  return ctx;
}

/** Returns the configured Client; throws if signed out (callers gate via routes). */
export function useClient(): Client {
  const { client } = useAuth();
  if (!client) throw new Error("not signed in");
  return client;
}
