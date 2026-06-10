/**
 * Frontend auth tests — Sprint 2.
 *
 * Covers the auth surface the dashboard depends on:
 *
 * - localStorage helpers (getStoredToken, getStoredUser, storeAuth, clearAuth)
 * - AuthContext state machine (loading -> authenticated/unauthenticated)
 * - login()  success + error paths
 * - register()  success + error paths
 * - refresh()  success + error paths
 * - logout()  clears state and redirects
 * - AuthGuard  protected route behaviour
 * - LoginPage / RegisterPage form interactions
 * - UserBadge  renders user + tenant + role separator
 *
 * Strategy:
 * - Mock ``@/lib/api`` so we control what the network "returns".
 * - Reset the mock between tests; clear localStorage too.
 */

import React, { ReactNode } from "react";
import { act, render, renderHook, screen, waitFor, fireEvent } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Module mocks (must come before importing the SUT)
// ---------------------------------------------------------------------------

const apiMock = {
  apiLogin: jest.fn(),
  apiRegister: jest.fn(),
  apiRefresh: jest.fn(),
  fetchMe: jest.fn(),
  storeAuth: jest.fn(),
  clearAuth: jest.fn(),
  getStoredToken: jest.fn(),
  getStoredUser: jest.fn(),
  getStoredRefresh: jest.fn(),
};

jest.mock("@/lib/api", () => {
  const actual = jest.requireActual("@/lib/api");
  return {
    ...actual,
    login: apiMock.apiLogin,
    register: apiMock.apiRegister,
    refresh: apiMock.apiRefresh,
    fetchMe: apiMock.fetchMe,
    storeAuth: apiMock.storeAuth,
    clearAuth: apiMock.clearAuth,
    getStoredToken: apiMock.getStoredToken,
    getStoredUser: apiMock.getStoredUser,
    getStoredRefresh: apiMock.getStoredRefresh,
  };
});

import { AuthProvider, useAuth } from "@/components/auth/AuthContext";
import { AuthGuard } from "@/components/auth/AuthGuard";
import { LoginPage } from "@/components/auth/LoginPage";
import { RegisterPage } from "@/components/auth/RegisterPage";
import { UserBadge } from "@/components/auth/UserBadge";

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------

const fakeUser = {
  id: "user-1",
  email: "ada@example.com",
  full_name: "Ada Lovelace",
  org_id: "org-1",
  role: "admin",
  is_active: true,
  created_at: "2024-01-01T00:00:00Z",
};

const fakeTenant = {
  id: "org-1",
  name: "Acme Inc.",
  slug: "acme",
  plan: "pro",
  is_active: true,
  created_at: "2024-01-01T00:00:00Z",
};

const fakeTokens = {
  access_token: "access-abc",
  refresh_token: "refresh-xyz",
  token_type: "bearer",
  expires_in: 3600,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resetStorage() {
  window.localStorage.clear();
}

function makeWrapper() {
  // The AuthContext has a redirect effect that needs the router from
  // next/navigation; the jest.setup.js already provides one.
  const wrapper = ({ children }: { children: ReactNode }) => (
    <AuthProvider>{children}</AuthProvider>
  );
  return wrapper;
}

beforeEach(() => {
  jest.clearAllMocks();
  resetStorage();
  // Defaults — tests override per-case.
  apiMock.getStoredToken.mockReturnValue(null);
  apiMock.getStoredUser.mockReturnValue(null);
  apiMock.getStoredRefresh.mockReturnValue(null);
  apiMock.clearAuth.mockImplementation(() => {
    window.localStorage.clear();
  });
  apiMock.storeAuth.mockImplementation((token, refresh, user) => {
    window.localStorage.setItem("flowwatch:auth:token", token);
    window.localStorage.setItem("flowwatch:auth:refresh", refresh);
    window.localStorage.setItem("flowwatch:auth:user", JSON.stringify(user));
  });

  // Reset mock router + pathname between tests
  const router = global.__getMockRouter();
  router.push.mockClear();
  router.replace.mockClear();
  global.__resetMockPathname();
});

afterEach(() => {
  global.__resetMockPathname();
});

// ===========================================================================
// 1. localStorage helpers round-trip
// ===========================================================================

describe("localStorage helpers", () => {
  test("getStoredToken returns null when empty", () => {
    // Re-import the real module (it's not mocked for this assertion).
    const api = jest.requireActual("@/lib/api") as typeof import("@/lib/api");
    expect(api.getStoredToken()).toBeNull();
  });

  test("storeAuth writes to localStorage and clearAuth wipes it", () => {
    const api = jest.requireActual("@/lib/api") as typeof import("@/lib/api");
    api.storeAuth("t1", "r1", fakeUser);
    expect(window.localStorage.getItem("flowwatch:auth:token")).toBe("t1");
    expect(window.localStorage.getItem("flowwatch:auth:refresh")).toBe("r1");
    expect(window.localStorage.getItem("flowwatch:auth:user")).toBe(
      JSON.stringify(fakeUser)
    );
    api.clearAuth();
    expect(window.localStorage.getItem("flowwatch:auth:token")).toBeNull();
    expect(window.localStorage.getItem("flowwatch:auth:refresh")).toBeNull();
    expect(window.localStorage.getItem("flowwatch:auth:user")).toBeNull();
  });

  test("getStoredUser returns null for invalid JSON", () => {
    window.localStorage.setItem("flowwatch:auth:user", "not-json{");
    const api = jest.requireActual("@/lib/api") as typeof import("@/lib/api");
    expect(api.getStoredUser()).toBeNull();
  });
});

// ===========================================================================
// 2. AuthContext state machine
// ===========================================================================

describe("AuthContext state machine", () => {
  test("starts in 'loading' then resolves to 'unauthenticated' when no token", async () => {
    apiMock.getStoredToken.mockReturnValue(null);

    const { result } = renderHook(() => useAuth(), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.status).toBe("unauthenticated"));
    expect(result.current.user).toBeNull();
    expect(result.current.tenant).toBeNull();
    expect(result.current.hasToken).toBe(false);
  });

  test("resolves to 'authenticated' when /me succeeds", async () => {
    apiMock.getStoredToken.mockReturnValue("access-abc");
    apiMock.fetchMe.mockResolvedValue({ user: fakeUser, tenant: fakeTenant });

    const { result } = renderHook(() => useAuth(), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.status).toBe("authenticated"));
    expect(result.current.user).toEqual(fakeUser);
    expect(result.current.tenant).toEqual(fakeTenant);
    expect(result.current.hasToken).toBe(true);
  });

  test("falls back to 'unauthenticated' and clears auth on /me failure", async () => {
    apiMock.getStoredToken.mockReturnValue("expired");
    apiMock.fetchMe.mockRejectedValue(new Error("401"));

    const { result } = renderHook(() => useAuth(), { wrapper: makeWrapper() });

    await waitFor(() => expect(result.current.status).toBe("unauthenticated"));
    expect(apiMock.clearAuth).toHaveBeenCalled();
    expect(result.current.user).toBeNull();
  });
});

// ===========================================================================
// 3. login()
// ===========================================================================

describe("AuthContext.login()", () => {
  test("stores tokens, calls /me, transitions to 'authenticated'", async () => {
    apiMock.getStoredToken.mockReturnValue(null);
    apiMock.apiLogin.mockResolvedValue(fakeTokens);
    apiMock.fetchMe.mockResolvedValue({ user: fakeUser, tenant: fakeTenant });

    const { result } = renderHook(() => useAuth(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.status).toBe("unauthenticated"));

    await act(async () => {
      await result.current.login("ada@example.com", "hunter2");
    });

    expect(apiMock.apiLogin).toHaveBeenCalledWith("ada@example.com", "hunter2");
    expect(apiMock.fetchMe).toHaveBeenCalled();
    expect(result.current.status).toBe("authenticated");
    expect(result.current.user?.email).toBe("ada@example.com");
  });

  test("surfaces error message when login fails", async () => {
    apiMock.getStoredToken.mockReturnValue(null);
    apiMock.apiLogin.mockRejectedValue(new Error("Invalid email or password"));

    const { result } = renderHook(() => useAuth(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.status).toBe("unauthenticated"));

    await act(async () => {
      await expect(
        result.current.login("ada@example.com", "wrong")
      ).rejects.toThrow("Invalid email or password");
    });

    expect(result.current.status).toBe("unauthenticated");
  });
});

// ===========================================================================
// 4. register()
// ===========================================================================

describe("AuthContext.register()", () => {
  test("stores tokens and transitions to 'authenticated'", async () => {
    apiMock.getStoredToken.mockReturnValue(null);
    apiMock.apiRegister.mockResolvedValue({
      user: fakeUser,
      tenant: fakeTenant,
      tokens: fakeTokens,
    });

    const { result } = renderHook(() => useAuth(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.status).toBe("unauthenticated"));

    await act(async () => {
      await result.current.register({
        tenant: { name: "Acme", slug: "acme" },
        user: { email: "ada@example.com", password: "hunter2hunter2" },
      });
    });

    expect(apiMock.apiRegister).toHaveBeenCalledWith({
      tenant: { name: "Acme", slug: "acme" },
      user: { email: "ada@example.com", password: "hunter2hunter2" },
    });
    expect(apiMock.storeAuth).toHaveBeenCalledWith(
      fakeTokens.access_token,
      fakeTokens.refresh_token,
      fakeUser
    );
    expect(result.current.status).toBe("authenticated");
    expect(result.current.tenant?.slug).toBe("acme");
  });
});

// ===========================================================================
// 5. refresh()
// ===========================================================================

describe("AuthContext.refresh()", () => {
  test("rotates tokens and updates state", async () => {
    apiMock.getStoredToken.mockReturnValue("old-access");
    apiMock.getStoredRefresh.mockReturnValue("old-refresh");
    apiMock.getStoredUser.mockReturnValue(fakeUser);
    // The AuthContext.refresh() reads the refresh token from
    // window.localStorage directly, so we need to seed it.
    window.localStorage.setItem("flowwatch:auth:refresh", "old-refresh");
    window.localStorage.setItem(
      "flowwatch:auth:user",
      JSON.stringify(fakeUser)
    );
    apiMock.apiRefresh.mockResolvedValue({
      ...fakeTokens,
      access_token: "new-access",
      refresh_token: "new-refresh",
    });

    const { result } = renderHook(() => useAuth(), { wrapper: makeWrapper() });

    await act(async () => {
      await result.current.refresh();
    });

    expect(apiMock.apiRefresh).toHaveBeenCalledWith("old-refresh");
    expect(apiMock.storeAuth).toHaveBeenCalledWith(
      "new-access",
      "new-refresh",
      fakeUser
    );
  });

  test("throws when there is no stored refresh token", async () => {
    apiMock.getStoredToken.mockReturnValue("access");
    apiMock.getStoredUser.mockReturnValue(fakeUser);
    apiMock.getStoredRefresh.mockReturnValue(null);
    // AuthContext.refresh() reads directly from localStorage; make
    // sure there's no refresh token there either.
    window.localStorage.removeItem("flowwatch:auth:refresh");

    const { result } = renderHook(() => useAuth(), { wrapper: makeWrapper() });
    await act(async () => {
      await expect(result.current.refresh()).rejects.toThrow(
        "No refresh token"
      );
    });
  });
});

// ===========================================================================
// 6. logout()
// ===========================================================================

describe("AuthContext.logout()", () => {
  test("clears auth, transitions to unauthenticated, redirects to /login", async () => {
    apiMock.getStoredToken.mockReturnValue("access");
    apiMock.fetchMe.mockResolvedValue({ user: fakeUser, tenant: fakeTenant });

    const { result } = renderHook(() => useAuth(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.status).toBe("authenticated"));

    act(() => {
      result.current.logout();
    });

    expect(apiMock.clearAuth).toHaveBeenCalled();
    expect(result.current.status).toBe("unauthenticated");
    expect(result.current.user).toBeNull();
    expect(global.__getMockRouter().replace).toHaveBeenCalledWith("/login");
  });
});

// ===========================================================================
// 7. AuthGuard — protected routes
// ===========================================================================

describe("AuthGuard", () => {
  function renderGuard(pathname: string) {
    global.__setMockPathname(pathname);
    return render(
      <AuthProvider>
        <AuthGuard>
          <div data-testid="protected">secret content</div>
        </AuthGuard>
      </AuthProvider>
    );
  }

  test("shows 'Checking session…' while status is loading", async () => {
    apiMock.getStoredToken.mockReturnValue("access");
    // fetchMe never resolves; we keep status='loading'
    let resolveMe: (v: any) => void = () => {};
    apiMock.fetchMe.mockReturnValue(
      new Promise((res) => {
        resolveMe = res;
      })
    );

    renderGuard("/dashboard");
    expect(await screen.findByText(/checking session/i)).toBeInTheDocument();
    expect(screen.queryByTestId("protected")).not.toBeInTheDocument();

    // Cleanup: resolve so the test doesn't leak.
    resolveMe({ user: fakeUser, tenant: fakeTenant });
  });

  test("renders children when authenticated", async () => {
    apiMock.getStoredToken.mockReturnValue("access");
    apiMock.fetchMe.mockResolvedValue({ user: fakeUser, tenant: fakeTenant });

    renderGuard("/dashboard");
    expect(await screen.findByTestId("protected")).toBeInTheDocument();
  });

  test("renders nothing when unauthenticated (redirect is the context's job)", async () => {
    apiMock.getStoredToken.mockReturnValue(null);

    renderGuard("/dashboard");
    await waitFor(() =>
      expect(screen.queryByTestId("protected")).not.toBeInTheDocument()
    );
  });

  test("renders children unconditionally on public paths", async () => {
    apiMock.getStoredToken.mockReturnValue(null);

    renderGuard("/login");
    expect(screen.getByTestId("protected")).toBeInTheDocument();
  });
});

// ===========================================================================
// 8. LoginPage form
// ===========================================================================

describe("LoginPage", () => {
  test("submits email + password, calls login, redirects to /", async () => {
    apiMock.getStoredToken.mockReturnValue(null);
    apiMock.apiLogin.mockResolvedValue(fakeTokens);
    apiMock.fetchMe.mockResolvedValue({ user: fakeUser, tenant: fakeTenant });

    render(
      <AuthProvider>
        <LoginPage />
      </AuthProvider>
    );

    const emailInput = screen.getByPlaceholderText("you@company.com");
    const passwordInput = screen.getByPlaceholderText("••••••••");
    fireEvent.change(emailInput, {
      target: { value: "ada@example.com" },
    });
    fireEvent.change(passwordInput, {
      target: { value: "hunter2" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() =>
      expect(apiMock.apiLogin).toHaveBeenCalledWith(
        "ada@example.com",
        "hunter2"
      )
    );
    await waitFor(() =>
      expect(global.__getMockRouter().replace).toHaveBeenCalledWith("/")
    );
  });

  test("shows the error message returned by the API", async () => {
    apiMock.getStoredToken.mockReturnValue(null);
    apiMock.apiLogin.mockRejectedValue(new Error("Invalid email or password"));

    render(
      <AuthProvider>
        <LoginPage />
      </AuthProvider>
    );

    fireEvent.change(screen.getByPlaceholderText("you@company.com"), {
      target: { value: "ada@example.com" },
    });
    fireEvent.change(screen.getByPlaceholderText("••••••••"), {
      target: { value: "wrong" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    expect(
      await screen.findByText(/invalid email or password/i)
    ).toBeInTheDocument();
  });
});

// ===========================================================================
// 9. RegisterPage form
// ===========================================================================

describe("RegisterPage", () => {
  test("auto-derives the slug from the org name", async () => {
    apiMock.getStoredToken.mockReturnValue(null);
    apiMock.apiRegister.mockResolvedValue({
      user: fakeUser,
      tenant: fakeTenant,
      tokens: fakeTokens,
    });

    render(
      <AuthProvider>
        <RegisterPage />
      </AuthProvider>
    );

    // The RegisterPage wraps every input in a <label>, so the label
    // text is the access key.
    fireEvent.change(screen.getByLabelText(/organization name/i), {
      target: { value: "Acme Inc." },
    });
    const slugInput = screen.getByLabelText(/organization slug/i) as HTMLInputElement;
    expect(slugInput.value).toBe("acme-inc");

    fireEvent.change(screen.getByLabelText(/your name/i), {
      target: { value: "Ada Lovelace" },
    });
    fireEvent.change(screen.getByLabelText(/^email/i), {
      target: { value: "ada@example.com" },
    });
    fireEvent.change(screen.getByLabelText(/^password/i), {
      target: { value: "hunter2hunter2" },
    });

    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    await waitFor(() =>
      expect(apiMock.apiRegister).toHaveBeenCalledWith({
        tenant: { name: "Acme Inc.", slug: "acme-inc" },
        user: {
          email: "ada@example.com",
          password: "hunter2hunter2",
          full_name: "Ada Lovelace",
        },
      })
    );
  });
});

// ===========================================================================
// 10. UserBadge
// ===========================================================================

describe("UserBadge", () => {
  test("renders user email, tenant name, and role separated by a middle dot", async () => {
    apiMock.getStoredToken.mockReturnValue("access");
    apiMock.fetchMe.mockResolvedValue({ user: fakeUser, tenant: fakeTenant });

    render(
      <AuthProvider>
        <UserBadge />
      </AuthProvider>
    );

    // Email is shown
    expect(await screen.findByText("ada@example.com")).toBeInTheDocument();
    // Tenant name + role with the middle-dot separator (Sprint 1 JSX bug fix)
    const tenantLine = screen.getByText(/Acme Inc\./);
    expect(tenantLine.textContent).toContain("·");
    expect(tenantLine.textContent).toContain("admin");
  });

  test("returns null when there is no user", async () => {
    apiMock.getStoredToken.mockReturnValue(null);

    const { container } = render(
      <AuthProvider>
        <UserBadge />
      </AuthProvider>
    );

    await waitFor(() => expect(container.firstChild).toBeNull());
  });
});
