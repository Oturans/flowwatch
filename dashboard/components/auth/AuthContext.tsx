"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  ReactNode,
} from "react";
import { useRouter, usePathname } from "next/navigation";
import {
  AuthUser,
  AuthTenant,
  MeResponse,
  TokenPair,
  clearAuth,
  fetchMe,
  getStoredToken,
  getStoredUser,
  login as apiLogin,
  refresh as apiRefresh,
  register as apiRegister,
  storeAuth,
  RegisterPayload,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// AuthContext — Sprint 1
// ---------------------------------------------------------------------------
//
// Single source of truth for "who is logged in". Persists the access
// token, refresh token, and the current user blob in localStorage so a
// page reload doesn't kick the user back to the login screen.
//
// Auto-redirects to /login on 401 from any wrapped fetch. (We catch
// the 401 in the api.ts fetchAPI and re-throw with a typed error;
// the auth context owns the redirect.)
// ---------------------------------------------------------------------------

interface AuthState {
  user: AuthUser | null;
  tenant: AuthTenant | null;
  token: string | null;
  status: "loading" | "authenticated" | "unauthenticated";
}

interface AuthContextValue extends AuthState {
  login: (email: string, password: string) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
  hasToken: boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const PUBLIC_PATHS = new Set<string>(["/login", "/register"]);

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();

  const [state, setState] = useState<AuthState>({
    user: null,
    tenant: null,
    token: null,
    status: "loading",
  });

  // Mount: pick up any persisted token and try to validate it.
  useEffect(() => {
    let cancelled = false;
    const init = async () => {
      const token = getStoredToken();
      if (!token) {
        if (!cancelled) {
          setState((s) => ({ ...s, status: "unauthenticated" }));
        }
        return;
      }

      try {
        const me: MeResponse = await fetchMe();
        if (cancelled) return;
        setState({
          user: me.user,
          tenant: me.tenant,
          token,
          status: "authenticated",
        });
      } catch (err: unknown) {
        // The token is stale; wipe it.
        clearAuth();
        if (!cancelled) {
          setState({
            user: null,
            tenant: null,
            token: null,
            status: "unauthenticated",
          });
        }
      }
    };
    init();
    return () => {
      cancelled = true;
    };
  }, []);

  // Auto-redirect to /login if unauthenticated on a protected page.
  useEffect(() => {
    if (state.status !== "unauthenticated") return;
    if (typeof pathname !== "string") return;
    if (PUBLIC_PATHS.has(pathname)) return;
    router.replace("/login");
  }, [state.status, pathname, router]);

  const login = useCallback(
    async (email: string, password: string) => {
      const tokens: TokenPair = await apiLogin(email, password);
      // Persist before the /me call so the bearer header is present.
      storeAuth(tokens.access_token, tokens.refresh_token, {
        // We don't yet have the user blob; stash a placeholder that
        // /me will overwrite momentarily.
        id: "",
        email,
        full_name: null,
        org_id: "",
        role: "",
        is_active: true,
        created_at: new Date().toISOString(),
      });
      const me = await fetchMe();
      storeAuth(tokens.access_token, tokens.refresh_token, me.user);
      setState({
        user: me.user,
        tenant: me.tenant,
        token: tokens.access_token,
        status: "authenticated",
      });
    },
    []
  );

  const register = useCallback(async (payload: RegisterPayload) => {
    const res = await apiRegister(payload);
    storeAuth(res.tokens.access_token, res.tokens.refresh_token, res.user);
    setState({
      user: res.user,
      tenant: res.tenant,
      token: res.tokens.access_token,
      status: "authenticated",
    });
  }, []);

  const refresh = useCallback(async () => {
    const stored = getStoredUser();
    if (!stored) throw new Error("No user to refresh");
    // We have a refresh token in localStorage; let api.refresh fetch
    // and persist a new pair.
    const cur =
      typeof window !== "undefined"
        ? window.localStorage.getItem("flowwatch:auth:refresh")
        : null;
    if (!cur) throw new Error("No refresh token");
    const tokens = await apiRefresh(cur);
    storeAuth(tokens.access_token, tokens.refresh_token, stored);
    setState((s) => ({ ...s, token: tokens.access_token }));
  }, []);

  const logout = useCallback(() => {
    clearAuth();
    setState({
      user: null,
      tenant: null,
      token: null,
      status: "unauthenticated",
    });
    router.replace("/login");
  }, [router]);

  const value = useMemo<AuthContextValue>(
    () => ({
      ...state,
      hasToken: !!state.token,
      login,
      register,
      logout,
      refresh,
    }),
    [state, login, register, logout, refresh]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return ctx;
}

/**
 * Convenience hook: returns the current org_id (tenant id) or null
 * when the user is not authenticated. Useful in components that need
 * to scope API calls.
 */
export function useOrgId(): string | null {
  const { user } = useAuth();
  return user?.org_id ?? null;
}
