import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { storage } from "@/src/utils/storage";
import { apiFetch, COOKIE_SESSION, TOKEN_KEY, UserPublic, Role, onAccountSuspended, deviceTimeZone } from "@/src/api";
import { registerForPush, unregisterPush } from "@/src/push";

interface AuthState {
  user: UserPublic | null;
  loading: boolean;
  suspended: boolean;
  clearSuspended: () => void;
  signIn: (email: string, password: string) => Promise<UserPublic>;
  signUp: (email: string, password: string, name: string, role: Role) => Promise<UserPublic>;
  signOut: () => Promise<void>;
  /** Signs out every phone and browser on this account. */
  signOutEverywhere: () => Promise<void>;
  refresh: () => Promise<void>;
  signInWithToken: (token: string, user: UserPublic) => Promise<void>;
  setUser: (user: UserPublic) => void;
}

const AuthCtx = createContext<AuthState | undefined>(undefined);

// Phone apps keep the token in encrypted device storage. The website never stores it: the API
// keeps the session in an HttpOnly cookie. (Removing also clears tokens older versions stored.)
const saveToken = async (token: string) => { if (!COOKIE_SESSION && token) await storage.secureSet(TOKEN_KEY, token); };
const forgetToken = () => storage.secureRemove(TOKEN_KEY);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserPublic | null>(null);
  const [loading, setLoading] = useState(true);
  const [suspended, setSuspended] = useState(false);

  const refresh = useCallback(async () => {
    try {
      if (COOKIE_SESSION) {
        await forgetToken();  // never keep a readable token in the browser
      } else if (!(await storage.secureGet<string>(TOKEN_KEY, ""))) {
        setUser(null); return;
      }
      const me = await apiFetch<UserPublic>("/auth/me");
      setUser(me);
    } catch {
      await forgetToken();
      setUser(null);
    }
  }, []);

  useEffect(() => {
    (async () => { await refresh(); setLoading(false); })();
  }, [refresh]);

  // A paused account gets signed out everywhere; AuthGate routes to /suspended.
  useEffect(() => {
    onAccountSuspended(async () => {
      await forgetToken();
      setSuspended(true);
      setUser(null);
    });
    return () => onAccountSuspended(null);
  }, []);

  // Once signed in: register this device for push, and keep the account's time zone current
  // so reminders arrive at the right local time.
  const userId = user?.id;
  useEffect(() => {
    if (!userId || !user) return;
    registerForPush();
    const tz = deviceTimeZone();
    if (tz && tz !== user.timezone && !user.is_admin) {
      apiFetch<UserPublic>("/auth/me", { method: "PATCH", body: JSON.stringify({ timezone: tz }) })
        .then(setUser)
        .catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  const signIn = async (email: string, password: string) => {
    const data = await apiFetch<{ access_token: string; user: UserPublic }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    await saveToken(data.access_token);
    setSuspended(false);
    setUser(data.user);
    return data.user;
  };

  const signUp = async (email: string, password: string, name: string, role: Role) => {
    const data = await apiFetch<{ access_token: string; user: UserPublic }>("/auth/signup", {
      method: "POST",
      body: JSON.stringify({ email, password, name, role, timezone: deviceTimeZone() }),
    });
    await saveToken(data.access_token);
    setUser(data.user);
    return data.user;
  };

  const signOut = async () => {
    await unregisterPush();
    if (COOKIE_SESSION) await apiFetch("/auth/logout", { method: "POST" }).catch(() => {});
    await forgetToken();
    setUser(null);
  };

  const signOutEverywhere = async () => {
    await apiFetch("/auth/logout-all", { method: "POST" });
    await forgetToken();
    setUser(null);
  };

  /** Use a token from a password reset to sign straight in. */
  const signInWithToken = async (token: string, u: UserPublic) => {
    await saveToken(token);
    setSuspended(false);
    setUser(u);
  };

  return (
    <AuthCtx.Provider value={{ user, loading, suspended, clearSuspended: () => setSuspended(false), signIn, signUp, signOut, signOutEverywhere, refresh, signInWithToken, setUser }}>
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth() {
  const v = useContext(AuthCtx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
