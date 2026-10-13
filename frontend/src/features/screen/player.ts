export function mapPoint(clientX: number, clientY: number, rect: Pick<DOMRect, "left" | "top" | "width" | "height">, width: number, height: number) {
    if (width <= 0 || height <= 0 || rect.width <= 0 || rect.height <= 0) throw new Error("Display geometry is unavailable.");
    const scale = Math.min(rect.width / width, rect.height / height);
    const left = rect.left + (rect.width - width * scale) / 2;
    const top = rect.top + (rect.height - height * scale) / 2;
    return { x: Math.max(0, Math.min(width - 1, Math.round((clientX - left) / scale))), y: Math.max(0, Math.min(height - 1, Math.round((clientY - top) / scale))), width, height };
}
export function h264Codec(data: Uint8Array): string | undefined {
    for (let i = 0; i + 3 < data.length; i++) {
        if (data[i] !== 0 || data[i + 1] !== 0) continue;
        const start = data[i + 2] === 1 ? i + 3 : data[i + 2] === 0 && data[i + 3] === 1 ? i + 4 : -1;
        if (start >= 0 && start + 3 < data.length && (data[start] & 31) === 7)
            return "avc1." + Array.from(data.slice(start + 1, start + 4)).map(v => v.toString(16).padStart(2, "0")).join("");
    }
}
export class ScreenDecoder {
    private decoder: VideoDecoder;
    private config = new Uint8Array();
    private waiting = true;
    private configured = false;
    private revision = 0;
    private decoderConfig?: VideoDecoderConfig;
    dropped = 0;
    received = 0;
    bytes = 0;
    constructor(output: (frame: VideoFrame) => void, error: (error: Error) => void) {
        this.decoder = new VideoDecoder({ output: frame => { try { output(frame); } finally { frame.close(); } }, error });
    }
    async packet(buffer: ArrayBuffer) {
        if (this.decoder.state === "closed") return;
        if (buffer.byteLength < 12 || buffer.byteLength > 8 * 1024 * 1024 + 12) throw new Error("Invalid video packet.");
        const header = new DataView(buffer), flags = header.getBigUint64(0);
        const payload = new Uint8Array(buffer, 12);
        if (header.getUint32(8) !== payload.length) throw new Error("Invalid video packet length.");
        if (flags & (1n << 63n)) {
            const revision = ++this.revision;
            this.configured = false;
            this.waiting = true;
            this.config = payload.slice();
            const codec = h264Codec(payload);
            if (!codec) throw new Error("H.264 configuration has no SPS.");
            const config: VideoDecoderConfig = { codec, optimizeForLatency: true };
            const supported = await VideoDecoder.isConfigSupported(config);
            if (!supported.supported) throw new Error("This browser cannot decode the device H.264 profile.");
            if ((this.decoder.state as string) === "closed" || revision !== this.revision) return;
            this.decoder.reset(); this.decoderConfig = config;
            this.decoder.configure(config); this.configured = true; this.waiting = true;
            return;
        }
        this.received++; this.bytes += buffer.byteLength;
        const key = Boolean(flags & (1n << 62n));
        if (!this.configured) { this.dropped++; return; }
        if (this.decoder.decodeQueueSize > 3) {
            this.decoder.reset();
            if (this.decoderConfig) this.decoder.configure(this.decoderConfig);
            this.waiting = true; this.dropped++; return;
        }
        if (this.waiting && !key) { this.dropped++; return; }
        this.waiting = false;
        const data = key ? new Uint8Array(this.config.length + payload.length) : payload;
        if (key) { data.set(this.config); data.set(payload, this.config.length); }
        this.decoder.decode(new EncodedVideoChunk({ type: key ? "key" : "delta", timestamp: Number(flags & ((1n << 62n) - 1n)), data }));
    }
    close() { this.revision++; if (this.decoder.state !== "closed") this.decoder.close(); }
}
