import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { Client } from "@ocr-to-report/sdk";

const KEY_STORAGE = "ocr2r:apiKey";
const URL_STORAGE = "ocr2r:baseUrl";
const DEFAULT_BASE_URL = "/api";

interface AuthState {
  apiKey: string | null;
  baseUrl: string;
  client: Client | null;
  signIn: (apiKey: string, baseUrl?: string) => void;
  signOut: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

function readStored(key: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  return window.localStorage.getItem(key) ?? fallback;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [apiKey, setApiKey] = useState<string | null>(() =>
    typeof window === "undefined" ? null : window.localStorage.getItem(KEY_STORAGE),
  );
  const [baseUrl, setBaseUrl] = useState<string>(() => readStored(URL_STORAGE, DEFAULT_BASE_URL));

  const client = useMemo<Client | null>(() => {
    if (!apiKey) return null;
    return new Client({ baseUrl, apiKey });
  }, [apiKey, baseUrl]);

  const value: AuthState = {
    apiKey,
    baseUrl,
    client,
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
      window.localStorage.removeItem(KEY_STORAGE);
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
