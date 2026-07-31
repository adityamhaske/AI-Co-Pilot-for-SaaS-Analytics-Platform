import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Testing Library does not auto-clean when `globals` is on for every runner version;
// doing it explicitly keeps DOM state from leaking between tests.
afterEach(cleanup);
