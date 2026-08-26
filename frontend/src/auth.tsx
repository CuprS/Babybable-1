import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { storage } from "@/src/utils/storage";
import { apiFetch, TOKEN_KEY, UserPublic, Role } from "@/src/api";

interface AuthState {
  user: UserPublic | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<UserPublic>;
  signUp: (email: string, password: string, name: string, role: Role) => Promise<UserPublic>;
  signOut: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthCtx = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserPublic | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const token = await storage.secureGet<string>(TOKEN_KEY, "");
      if (!token) { setUser(null); return; }
      const me = await apiFetch<UserPublic>("/auth/me");
      setUser(me);
    } catch {
      await storage.secureRemove(TOKEN_KEY);
      setUser(null);
    }
  }, []);

  useEffect(() => {
    (async () => { await refresh(); setLoading(false); })();
  }, [refresh]);

  const signIn = async (email: string, password: string) => {
    const data = await apiFetch<{ access_token: string; user: UserPublic }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    await storage.secureSet(TOKEN_KEY, data.access_token);
    setUser(data.user);
    return data.user;
  };

  const signUp = async (email: string, password: string, name: string, role: Role) => {
    const data = await apiFetch<{ access_token: string; user: UserPublic }>("/auth/signup", {
      method: "POST",
      body: JSON.stringify({ email, password, name, role }),
    });
    await storage.secureSet(TOKEN_KEY, data.access_token);
    setUser(data.user);
    return data.user;
  };

  const signOut = async () => {
    await storage.secureRemove(TOKEN_KEY);
    setUser(null);
  };

  return (
    <AuthCtx.Provider value={{ user, loading, signIn, signUp, signOut, refresh }}>
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth() {
  const v = useContext(AuthCtx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
