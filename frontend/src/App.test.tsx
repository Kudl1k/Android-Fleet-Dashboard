import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const setToken = vi.fn();
vi.mock("./lib/auth", () => ({
    useAuth: () => ({ token: "", identity: undefined, error: "", can: () => false, setToken }),
}));
vi.mock("./lib/alertNotifications", () => ({ useAlertNotifications: () => {} }));
vi.mock("./features/fleet/FleetPage", () => ({ default: () => <h1>Fleet overview</h1> }));
vi.mock("./features/alerts/AlertsPage", () => ({ default: () => <h1>Alerts</h1> }));

function show() {
    return render(<MemoryRouter><App /></MemoryRouter>);
}

beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
        this.setAttribute("open", "");
    });
});

describe("application navigation and access", () => {
    it("closes navigation with Escape and returns focus to its toggle", async () => {
        show();
        await screen.findByRole("heading", { name: "Fleet overview" });
        const toggle = screen.getByRole("button", { name: "Open navigation" });
        fireEvent.click(toggle);
        expect(toggle).toHaveAttribute("aria-expanded", "true");
        const navigation = screen.getByRole("navigation", { name: "Main navigation" });
        within(navigation).getByRole("link", { name: "Alerts" }).focus();
        fireEvent.keyDown(document.activeElement!, { key: "Escape" });
        expect(toggle).toHaveAttribute("aria-expanded", "false");
        expect(toggle).toHaveFocus();
    });

    it("closes navigation after selecting a route and updates the page title", async () => {
        show();
        fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
        fireEvent.click(screen.getByRole("link", { name: "Alerts" }));
        await screen.findByRole("heading", { name: "Alerts" });
        expect(screen.getByRole("button", { name: "Open navigation" })).toHaveAttribute("aria-expanded", "false");
        expect(document.title).toBe("Alerts · Android Fleet");
        expect(screen.getByRole("main")).toHaveFocus();
        expect(window.scrollTo).toHaveBeenCalledWith(0, 0);
    });

    it("discards a cancelled token draft and restores focus to the access trigger", async () => {
        show();
        const trigger = screen.getAllByRole("button", { name: "Sign in" })[0];
        trigger.focus();
        fireEvent.click(trigger);
        const dialog = screen.getByRole("dialog", { name: "Fleet access" });
        fireEvent.change(within(dialog).getByLabelText("Control token"), { target: { value: "discard-me" } });
        fireEvent(dialog, new Event("cancel"));
        await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
        expect(trigger).toHaveFocus();
        expect(setToken).not.toHaveBeenCalled();
        fireEvent.click(trigger);
        expect(screen.getByLabelText("Control token")).toHaveValue("");
    });
});
