/**
 * Type augmentations for the test helpers and custom matchers.
 *
 * This file is auto-included by tsconfig.json (``**\/*.ts``). It
 * augments the global scope with the helpers from ``jest.setup.js``
 * and adds the ``toBeInTheDocument`` matcher.
 */

/// <reference path="./test-helpers.d.ts" />

export {};

declare global {
  // eslint-disable-next-line no-var
  var __setMockPathname: (p: string) => void;
  // eslint-disable-next-line no-var
  var __resetMockPathname: () => void;
  // eslint-disable-next-line no-var
  var __getMockRouter: () => import("./test-helpers").AuthRouterMock;
  // eslint-disable-next-line no-var
  var __resetMockRouter: () => void;

  namespace jest {
    interface Matchers<R> {
      toBeInTheDocument(): R;
    }
  }
}
