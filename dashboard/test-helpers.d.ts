/**
 * Type definitions shared by tests and jest.setup.js.
 *
 * We keep this in a single place so the test files and the setup
 * file agree on the shape of the mocked router and helpers.
 */

export interface AuthRouterMock {
  push: jest.Mock;
  replace: jest.Mock;
  refresh: jest.Mock;
  back: jest.Mock;
  forward: jest.Mock;
  prefetch: jest.Mock;
}
