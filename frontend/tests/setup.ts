import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Testing Library does not auto-clean when `globals` is on for every runner version;
// doing it explicitly keeps DOM state from leaking between tests.
afterEach(cleanup);

// jsdom implements no layout, so scrollIntoView does not exist. MessageList calls it on
// every render to keep the thread pinned to the newest turn. Stubbed rather than guarded
// in the component: the guard would exist only for the test environment.
Element.prototype.scrollIntoView = vi.fn();
