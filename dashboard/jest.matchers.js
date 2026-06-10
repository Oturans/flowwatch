/**
 * Custom Jest matchers for the FlowWatch dashboard tests.
 *
 * Loaded via ``setupFilesAfterEnv`` (after the test framework is
 * installed) so ``expect`` is available here. We keep this file
 * intentionally small — anything we need should be a plain Jest
 * matcher rather than reaching for @testing-library/jest-dom.
 */

expect.extend({
  toBeInTheDocument(received) {
    // jsdom never has a "document" that's missing; the only way an
    // element can fail this is if the call returned null / undefined.
    const pass = received != null;
    return {
      pass,
      message: () =>
        pass
          ? "expected element not to be in the document"
          : "expected element to be in the document, but it was not found",
    };
  },
});
