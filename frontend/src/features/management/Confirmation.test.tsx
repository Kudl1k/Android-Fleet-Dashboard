import { StrictMode, useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import Confirmation from "./Confirmation";

afterEach(() => vi.restoreAllMocks());
it("restores the opener after modal autofocus and StrictMode effect replay", () => {
    HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
        this.open = true;
        this.querySelector<HTMLButtonElement>("button")?.focus();
    });
    const close = vi.spyOn(HTMLDialogElement.prototype, "close").mockImplementation(function (this: HTMLDialogElement) { this.open = false; });
    function Example() {
        const [open, setOpen] = useState(false);
        return <><button onClick={() => setOpen(true)}>Open device action</button>{open && <Confirmation title="Confirm device action" onCancel={() => setOpen(false)}><button autoFocus onClick={() => setOpen(false)}>Cancel</button></Confirmation>}</>;
    }
    render(<StrictMode><Example /></StrictMode>);
    const opener = screen.getByRole("button", {name: "Open device action"});
    opener.focus(); fireEvent.click(opener);
    expect(screen.getByRole("dialog", {name: "Confirm device action"})).toBeInTheDocument();
    expect(screen.getByRole("button", {name: "Cancel"})).toHaveFocus();
    fireEvent.click(screen.getByRole("button", {name: "Cancel"}));
    expect(opener).toHaveFocus();
    expect(close).toHaveBeenCalled();
});
