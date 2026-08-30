import "@testing-library/jest-dom/vitest";

/**
 * Browser APIs jsdom does not implement.
 *
 * Both are read by components that ask the environment about itself rather than about
 * the page — reduced-motion preference, and element size. jsdom has neither, so without
 * these a screen that behaves correctly in a browser throws on mount in a test, and the
 * test tells you nothing about the code.
 *
 * `matches: false` is the honest default: a test environment has expressed no preference,
 * so components take their ordinary path and the animated branch is the one under test.
 */
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    media: query,
    matches: false,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

if (!window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}
