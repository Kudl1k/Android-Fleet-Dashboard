import { describe, it, expect, vi, afterEach } from "vitest";
import {
    AUTH_EXPIRED_EVENT,
    request,
    protectedImage,
    setControlToken,
    metricValue,
    formatMetric,
    type CurrentMetrics,
} from "./api";
import { chartPoints } from "../features/fleet/DevicePage";
afterEach(() => {
    setControlToken("");
    vi.unstubAllGlobals();
});
describe("API integration", () => {
    it("adds memory token and handles structured authorization errors", async () => {
        const fetch = vi
            .fn()
            .mockResolvedValue(
                new Response(
                    JSON.stringify({ error: { message: "Not authorized" } }),
                    { status: 401 },
                ),
            );
        vi.stubGlobal("fetch", fetch);
        setControlToken("private");
        await expect(
            request("/api/v1/devices", { method: "POST", body: "{}" }),
        ).rejects.toThrow("Not authorized");
        expect(
            new Headers(fetch.mock.calls[0][1].headers).get("Authorization"),
        ).toBe("Bearer private");
        expect(localStorage.getItem("private")).toBeNull();
    });
    it("remembers the token across reloads and forgets it on sign-out or rejection", async () => {
        setControlToken("kept");
        expect(localStorage.getItem("fleet-control-token")).toBe("kept");
        vi.resetModules();
        const reloaded = await import("./api");
        expect(reloaded.getControlToken()).toBe("kept");
        reloaded.setControlToken("");
        expect(localStorage.getItem("fleet-control-token")).toBeNull();
        vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })));
        reloaded.setControlToken("revoked");
        await expect(reloaded.request("/api/v1/devices")).rejects.toThrow();
        expect(localStorage.getItem("fleet-control-token")).toBeNull();
    });
    it("fetches screenshots with the memory credential and rejects denied images", async () => {
        const fetch = vi.fn().mockResolvedValueOnce(new Response("png", {headers:{"Content-Type":"image/png"}})).mockResolvedValueOnce(new Response(null, {status:403}));
        vi.stubGlobal("fetch", fetch);
        setControlToken("private");
        const blob = await protectedImage("/api/v1/operations/a/screenshot");
        expect(blob.type).toBe("image/png");
        expect(new Headers(fetch.mock.calls[0][1].headers).get("Authorization")).toBe("Bearer private");
        expect(fetch.mock.calls[0][1].credentials).toBe("omit");
        await expect(protectedImage("/api/v1/operations/a/screenshot")).rejects.toThrow("access denied");
    });
    it("expires an invalid credential and stops sending it", async () => {
        const expired = vi.fn();
        window.addEventListener(AUTH_EXPIRED_EVENT, expired);
        const fetch = vi.fn().mockResolvedValueOnce(new Response(null, {status:401})).mockResolvedValueOnce(new Response("{}"));
        vi.stubGlobal("fetch", fetch);
        setControlToken("expired");
        await expect(request("/api/v1/devices")).rejects.toThrow();
        await request("/api/v1/devices");
        expect(expired).toHaveBeenCalledOnce();
        expect(new Headers(fetch.mock.calls[1][1].headers).has("Authorization")).toBe(false);
        window.removeEventListener(AUTH_EXPIRED_EVENT, expired);
    });
    it("rejects screenshots finishing after credentials change", async () => {
        vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => {
            setControlToken("replacement");
            return new Response("png", {headers:{"Content-Type":"image/png"}});
        }));
        setControlToken("original");
        await expect(protectedImage("/api/v1/operations/a/screenshot")).rejects.toThrow("Access changed");
    });
    it("does not expire a replacement credential for a previous request", async () => {
        const expired = vi.fn();
        window.addEventListener(AUTH_EXPIRED_EVENT, expired);
        vi.stubGlobal("fetch", vi.fn().mockImplementation(async () => {
            setControlToken("replacement");
            return new Response(null, {status:401});
        }));
        setControlToken("original");
        await expect(request("/api/v1/devices")).rejects.toThrow();
        expect(expired).not.toHaveBeenCalled();
        window.removeEventListener(AUTH_EXPIRED_EVENT, expired);
    });
    it("handles no-content deletion", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue(new Response(null, { status: 204 })),
        );
        await expect(
            request("/api/v1/devices/id", { method: "DELETE" }),
        ).resolves.toBeUndefined();
    });
    it("withholds stale and disconnected values while preserving observed zero", () => {
        const metrics: CurrentMetrics = {
            device_id: "a",
            state: "online",
            stale: false,
            observed_at: "2026-01-01",
            values: [
                {
                    name: "cpu_usage",
                    value: 0,
                    unit: "ratio",
                    kind: "gauge",
                    labels: {},
                },
            ],
        };
        expect(metricValue(metrics, "cpu_usage")).toBe(0);
        expect(
            metricValue({ ...metrics, stale: true }, "cpu_usage"),
        ).toBeNull();
        expect(
            metricValue({ ...metrics, state: "offline" }, "cpu_usage"),
        ).toBeNull();
        expect(formatMetric(null, "ratio")).toBe("Unavailable");
        expect(formatMetric(0, "ratio")).toBe("0.0%");
    });
    it("inserts history gaps rather than joining disconnected periods", () => {
        const point = {
            name: "cpu_usage",
            value: 0.5,
            unit: "ratio",
            kind: "gauge",
            labels: {},
        };
        const result = chartPoints([
            { ...point, observed_at: "2026-01-01T00:00:00Z" },
            { ...point, observed_at: "2026-01-01T00:03:00Z" },
        ]);
        expect(result.map((p) => p.value)).toEqual([50, null, 50]);
    });
});
