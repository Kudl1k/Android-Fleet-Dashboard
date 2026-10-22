import { act, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ListRegion from "./ListRegion";

afterEach(() => vi.unstubAllGlobals());
it("describes actual overflow, removes the hint for short content and preserves the scroll target", () => {
    const observers: ResizeObserverCallback[] = [];
    const disconnect = vi.fn();
    vi.stubGlobal(
        "ResizeObserver",
        class {
            constructor(callback: ResizeObserverCallback) {
                observers.push(callback);
            }
            observe() {}
            unobserve() {}
            disconnect = disconnect;
        },
    );
    const view = render(
        <ListRegion label="Device records">
            <ul>
                <li>Long record</li>
            </ul>
        </ListRegion>,
    );
    const region = screen.getByRole("region", { name: "Device records" });
    expect(region).toHaveAttribute("tabindex", "0");
    expect(screen.queryByText("Scroll for more items")).not.toBeInTheDocument();
    Object.defineProperty(region, "clientHeight", {
        configurable: true,
        value: 200,
    });
    Object.defineProperty(region, "scrollHeight", {
        configurable: true,
        value: 1000,
    });
    act(() => observers.forEach((notify) => notify([], {} as ResizeObserver)));
    expect(region).toHaveAccessibleDescription("Scroll for more items");
    region.scrollTop = 180;
    Object.defineProperty(region, "scrollHeight", {
        configurable: true,
        value: 200,
    });
    act(() => observers.forEach((notify) => notify([], {} as ResizeObserver)));
    expect(region).not.toHaveAttribute("aria-describedby");
    expect(region.scrollTop).toBe(180);
    view.unmount();
    expect(disconnect).toHaveBeenCalled();
});
