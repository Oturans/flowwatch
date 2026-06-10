/**
 * Jest test setup. Runs once per test file, before any test executes.
 *
 * Polyfills / mocks:
 *
 * - ``next/navigation``: stub the router and pathname hooks used by
 *   AuthProvider/AuthGuard so component tests don't need a real Next
 *   runtime.
 * - ``@testing-library/jest-dom``: not yet a dep; we provide a tiny
 *   custom matcher set so we don't have to install another package.
 *
 * The tests are written to be self-contained: each test sets its own
 * mock return values via ``mockRouter`` / ``mockPathname`` etc.
 */

// Polyfill TextEncoder / TextDecoder for React Query and other libs
// that expect them in jsdom.
const { TextEncoder, TextDecoder } = require("util");
if (typeof globalThis.TextEncoder === "undefined") {
  globalThis.TextEncoder = TextEncoder;
}
if (typeof globalThis.TextDecoder === "undefined") {
  globalThis.TextDecoder = TextDecoder;
}

// ---------------------------------------------------------------------------
// next/navigation mocks
// ---------------------------------------------------------------------------

const mockRouter = {
  push: jest.fn(),
  replace: jest.fn(),
  refresh: jest.fn(),
  back: jest.fn(),
  forward: jest.fn(),
  prefetch: jest.fn(),
};

let mockPathnameValue = "/";
let mockSearchParamsValue = new URLSearchParams();

jest.mock("next/navigation", () => ({
  useRouter: () => mockRouter,
  usePathname: () => mockPathnameValue,
  useSearchParams: () => mockSearchParamsValue,
}));

// Expose setters so tests can change behaviour mid-run.
global.__setMockPathname = (p) => {
  mockPathnameValue = p;
};
global.__resetMockPathname = () => {
  mockPathnameValue = "/";
};
global.__getMockRouter = () => mockRouter;
global.__resetMockRouter = () => {
  mockRouter.push.mockClear();
  mockRouter.replace.mockClear();
  mockRouter.refresh.mockClear();
  mockRouter.back.mockClear();
  mockRouter.forward.mockClear();
  mockRouter.prefetch.mockClear();
};

// ---------------------------------------------------------------------------
// localStorage shim (jsdom provides one, but make sure it always exists)
// ---------------------------------------------------------------------------
if (typeof globalThis.localStorage === "undefined") {
  const store = new Map();
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
    clear: () => store.clear(),
    key: (i) => Array.from(store.keys())[i] || null,
    get length() {
      return store.size;
    },
  };
}
