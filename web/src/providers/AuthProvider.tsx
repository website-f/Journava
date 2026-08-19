import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  type AuthUser,
  fetchMe,
  login as apiLogin,
  logout as apiLogout,
  refreshAccessToken,
  registerAccount as apiRegister,
  setAuthFailureHandler,
} from "@/lib/auth";

type Status = "loading" | "authed" | "guest";

type AuthContextValue = {
  status: Status;
  user: AuthUser | null;
  isPlatformAdmin: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, displayName?: string) => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [user, setUser] = useState<AuthUser | null>(null);

  // Restore a session on first load: the httpOnly refresh cookie (if any) mints
  // a fresh access token, then /me hydrates the user.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const token = await refreshAccessToken();
      const me = token ? await fetchMe() : null;
      if (cancelled) return;
      setUser(me);
      setStatus(me ? "authed" : "guest");
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // api.ts triggers this when a request fails auth even after a refresh.
  useEffect(() => {
    setAuthFailureHandler(() => {
      setUser(null);
      setStatus("guest");
    });
    return () => setAuthFailureHandler(null);
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const u = await apiLogin(email, password);
    setUser(u);
    setStatus("authed");
  }, []);

  const signUp = useCallback(
    async (email: string, password: string, displayName?: string) => {
      const u = await apiRegister(email, password, displayName);
      setUser(u);
      setStatus("authed");
    },
    [],
  );

  const signOut = useCallback(async () => {
    await apiLogout();
    setUser(null);
    setStatus("guest");
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      isPlatformAdmin: Boolean(user?.is_platform_admin),
      signIn,
      signUp,
      signOut,
    }),
    [status, user, signIn, signUp, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
