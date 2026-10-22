import { StrictMode, useState } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import Confirmation from "./Confirmation";

afterEach(() => vi.restoreAllMocks());
it("restores the opener after modal autofocus and StrictMode effect replay", async () => {
    function Example() {
        const [open, setOpen] = useState(false);
        return (
            <>
                <button onClick={() => setOpen(true)}>
                    Open device action
                </button>
                {open && (
                    <Confirmation
                        title="Confirm device action"
                        onCancel={() => setOpen(false)}
                    >
                        <button autoFocus onClick={() => setOpen(false)}>
                            Cancel
                        </button>
                    </Confirmation>
                )}
            </>
        );
    }
    render(
        <StrictMode>
            <Example />
        </StrictMode>,
    );
    const opener = screen.getByRole("button", { name: "Open device action" });
    opener.focus();
    fireEvent.click(opener);
    expect(
        screen.getByRole("alertdialog", { name: "Confirm device action" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(opener).toHaveFocus());
});

it("cancels on Escape and returns keyboard focus to the opener", async () => {
    function Example() {
        const [open, setOpen] = useState(false);
        return (
            <>
                <button onClick={() => setOpen(true)}>Restart</button>
                {open && (
                    <Confirmation
                        title="Confirm restart"
                        onCancel={() => setOpen(false)}
                    >
                        <button>Cancel</button>
                        <button>Confirm action</button>
                    </Confirmation>
                )}
            </>
        );
    }
    render(<Example />);
    const opener = screen.getByRole("button", { name: "Restart" });
    opener.focus();
    fireEvent.click(opener);
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    await waitFor(() =>
        expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(opener).toHaveFocus();
});
