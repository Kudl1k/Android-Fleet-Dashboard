import { describe, expect, it, vi } from "vitest";
import { h264Codec, mapPoint, ScreenDecoder } from "./player";
describe("screen geometry and decoder", () => {
    it("maps letterboxed coordinates and clamps outside the display", () => {
        const rect = { left: 10, top: 20, width: 1000, height: 600 };
        expect(mapPoint(510, 320, rect, 300, 600)).toEqual({ x: 150, y: 300, width: 300, height: 600 });
        expect(mapPoint(0, 9999, rect, 300, 600)).toEqual({ x: 0, y: 599, width: 300, height: 600 });
    });
    it("maps rotated and high DPI video dimensions", () => {
        expect(mapPoint(250, 125, { left: 0, top: 0, width: 500, height: 250 }, 2000, 1000)).toEqual({ x: 1000, y: 500, width: 2000, height: 1000 });
    });
    it("extracts H264 profile from three and four byte Annex B start codes", () => {
        expect(h264Codec(new Uint8Array([0, 0, 0, 1, 103, 100, 0, 42, 1]))).toBe("avc1.64002a");
        expect(h264Codec(new Uint8Array([0, 0, 1, 103, 66, 128, 31, 1]))).toBe("avc1.42801f");
        expect(h264Codec(new Uint8Array([0, 0, 1, 103, 244, 0, 40]))).toBe("avc1.f40028");
        expect(h264Codec(new Uint8Array([0, 0, 1, 103, 66, 128, 31]))).toBe("avc1.42801f");
        expect(h264Codec(new Uint8Array([0, 0, 1, 103, 66, 128]))).toBeUndefined();
        expect(h264Codec(new Uint8Array([1, 2, 3]))).toBeUndefined();
    });
    it("rejects malformed packets and drops delta frames before configuration", async () => {
        vi.stubGlobal("VideoDecoder", class { state = "unconfigured"; close() { this.state = "closed"; } });
        const decoder = new ScreenDecoder(vi.fn(), vi.fn());
        await expect(decoder.packet(new ArrayBuffer(2))).rejects.toThrow("Invalid video packet");
        await decoder.packet(new ArrayBuffer(12)); expect(decoder.dropped).toBe(1);
        decoder.close(); vi.unstubAllGlobals();
    });
});

function packet(flags: bigint, payload = new Uint8Array()) {
    const bytes = new Uint8Array(12 + payload.length);
    const header = new DataView(bytes.buffer);
    header.setBigUint64(0, flags); header.setUint32(8, payload.length); bytes.set(payload, 12);
    return bytes.buffer;
}
const configPacket = () => packet(1n << 63n, new Uint8Array([0, 0, 0, 1, 103, 66, 128, 31, 1]));
class DecoderFixture {
    static current: DecoderFixture;
    static isConfigSupported = vi.fn(async () => ({ supported: true }));
    state = "unconfigured"; decodeQueueSize = 0;
    configure = vi.fn(() => { this.state = "configured"; });
    reset = vi.fn(() => { this.state = "unconfigured"; this.decodeQueueSize = 0; });
    decode = vi.fn(); close = vi.fn(() => { this.state = "closed"; });
    constructor(public callbacks: { output: (frame: VideoFrame) => void }) { DecoderFixture.current = this; }
}
describe("decoder rotation and resource recovery", () => {
    it("reconfigures rotation, waits for keyframes and resets overloaded decoding", async () => {
        vi.stubGlobal("VideoDecoder", DecoderFixture); vi.stubGlobal("EncodedVideoChunk", class { constructor(public data: unknown) {} });
        const decoder = new ScreenDecoder(vi.fn(), vi.fn());
        await decoder.packet(configPacket());
        await decoder.packet(packet(0n)); expect(decoder.dropped).toBe(1);
        await decoder.packet(packet(1n << 62n)); expect(DecoderFixture.current.decode).toHaveBeenCalledTimes(1);
        DecoderFixture.current.decodeQueueSize = 4;
        await decoder.packet(packet(0n)); expect(DecoderFixture.current.reset).toHaveBeenCalledTimes(2);
        await decoder.packet(packet(0n)); expect(decoder.dropped).toBe(3);
        await decoder.packet(configPacket()); expect(DecoderFixture.current.configure).toHaveBeenCalledTimes(3);
        await decoder.packet(packet(1n << 62n)); expect(DecoderFixture.current.decode).toHaveBeenCalledTimes(2);
        decoder.close(); await decoder.packet(packet(1n << 62n)); expect(DecoderFixture.current.decode).toHaveBeenCalledTimes(2);
        vi.unstubAllGlobals();
    });
    it("ignores codec negotiation completing after close", async () => {
        vi.stubGlobal("VideoDecoder", DecoderFixture);
        let finish!: (result: { supported: boolean }) => void;
        DecoderFixture.isConfigSupported.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
        const decoder = new ScreenDecoder(vi.fn(), vi.fn()); const pending = decoder.packet(configPacket()); decoder.close(); finish({ supported: true }); await pending;
        expect(DecoderFixture.current.configure).not.toHaveBeenCalled(); vi.unstubAllGlobals();
    });
    it("rejects unsupported H264 profiles and always closes output frames", async () => {
        vi.stubGlobal("VideoDecoder", DecoderFixture);
        DecoderFixture.isConfigSupported.mockResolvedValueOnce({ supported: false });
        const output = vi.fn(() => { throw new Error("canvas unavailable"); }); const decoder = new ScreenDecoder(output, vi.fn());
        await expect(decoder.packet(configPacket())).rejects.toThrow("cannot decode");
        const frame = { close: vi.fn() } as unknown as VideoFrame;
        expect(() => DecoderFixture.current.callbacks.output(frame)).toThrow("canvas unavailable"); expect(frame.close).toHaveBeenCalledOnce(); decoder.close(); vi.unstubAllGlobals();
    });
    it("maps portrait, landscape and resized/fullscreen/mobile viewports using current dimensions", () => {
        for (const [width, height] of [[720, 1280], [1280, 720], [1080, 2340]]) {
            for (const [rw, rh] of [[390, 844], [1920, 1080], [300, 300]]) {
                expect(mapPoint(rw / 2, rh / 2, { left: 0, top: 0, width: rw, height: rh }, width, height)).toEqual({ x: width / 2, y: height / 2, width, height });
            }
        }
        expect(() => mapPoint(0, 0, { left: 0, top: 0, width: 0, height: 0 }, 720, 1280)).toThrow("geometry");
    });
});
