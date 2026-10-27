import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Meter from "./Meter";
import StatusChip from "./StatusChip";
import { relativeTime } from "../lib/time";

describe("lab bench primitives", () => {
    it("renders a missing meter value as an empty track, never zero", () => {
        const { container } = render(<Meter label="CPU" value={null} display="Unavailable" />);
        expect(screen.getByText("Unavailable")).toBeInTheDocument();
        expect(container.querySelector(".meter")).toHaveAttribute("data-tone", "none");
        expect(container.querySelector(".meter-fill")).toBeNull();
    });
    it("tones meters by load, and inverted meters by shortage", () => {
        const { container, rerender } = render(<Meter label="RAM" value={0.95} display="95%" />);
        expect(container.querySelector(".meter")).toHaveAttribute("data-tone", "critical");
        rerender(<Meter label="Battery" value={0.2} display="20%" warn={0.7} critical={0.85} invert />);
        expect(container.querySelector(".meter")).toHaveAttribute("data-tone", "warn");
    });
    it("keeps state text beside the coloured LED", () => {
        render(<StatusChip value="timed_out" />);
        const chip = screen.getByText("timed out");
        expect(chip).toHaveAttribute("data-tone", "critical");
        render(<StatusChip value="something_new" />);
        expect(screen.getByText("something new")).toHaveAttribute("data-tone", "off");
    });
    it("formats relative times", () => {
        const now = Date.parse("2026-10-25T12:00:00Z");
        expect(relativeTime(null, now)).toBe("never");
        expect(relativeTime("2026-10-25T11:59:55Z", now)).toBe("just now");
        expect(relativeTime("2026-10-25T11:59:30Z", now)).toBe("30 s ago");
        expect(relativeTime("2026-10-25T11:15:00Z", now)).toBe("45 min ago");
        expect(relativeTime("2026-10-25T07:00:00Z", now)).toBe("5 h ago");
        expect(relativeTime("2026-10-20T12:00:00Z", now)).toBe("5 d ago");
    });
});
