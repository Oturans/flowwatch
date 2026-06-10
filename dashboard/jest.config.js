/**
 * Jest configuration for FlowWatch dashboard.
 *
 * Uses ts-jest for TypeScript transpilation, jsdom for a browser-like
 * environment, and the standard @testing-library/react for component
 * rendering. The path alias '@/*' mirrors the tsconfig.json setup so
 * tests can import from '@/lib/...' and '@/components/...'.
 */
/** @type {import('jest').Config} */
module.exports = {
  testEnvironment: "jsdom",
  setupFiles: ["<rootDir>/jest.setup.js"],
  setupFilesAfterEnv: ["<rootDir>/jest.matchers.js"],
  testMatch: [
    "<rootDir>/__tests__/**/*.test.{ts,tsx}",
    "<rootDir>/components/**/*.test.{ts,tsx}",
    "<rootDir>/lib/**/*.test.{ts,tsx}",
  ],
  moduleFileExtensions: ["ts", "tsx", "js", "jsx", "json"],
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/$1",
  },
  transform: {
    "^.+\\.(ts|tsx)$": [
      "ts-jest",
      {
        tsconfig: {
          jsx: "react-jsx",
          esModuleInterop: true,
          allowJs: true,
          module: "commonjs",
          target: "es2020",
          lib: ["dom", "dom.iterable", "esnext"],
          strict: true,
          skipLibCheck: true,
          resolveJsonModule: true,
          isolatedModules: true,
          moduleResolution: "node",
        },
        diagnostics: {
          ignoreCodes: [151001], // suppress ts-jest's "type definitions" warning
        },
      },
    ],
  },
  transformIgnorePatterns: ["/node_modules/(?!(next|@testing-library)/)"],
  testPathIgnorePatterns: ["/node_modules/", "/.next/"],
  collectCoverageFrom: [
    "components/**/*.{ts,tsx}",
    "lib/**/*.{ts,tsx}",
    "app/**/*.{ts,tsx}",
    "!**/*.d.ts",
  ],
  clearMocks: true,
  resetModules: true,
};
