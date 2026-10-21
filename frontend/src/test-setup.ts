import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";
afterEach(cleanup);

// jsdom has no native dialog close implementation. Match the open-state behavior
// so modal cleanup and StrictMode replay can be exercised without a browser.
HTMLDialogElement.prototype.close = function () {
    this.open = false;
    this.dispatchEvent(new Event("close"));
};
