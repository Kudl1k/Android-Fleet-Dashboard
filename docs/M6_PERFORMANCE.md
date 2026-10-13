# M6 streaming performance

Hardware/environment: Samsung SM-A356B, non-rooted Android 16 over Wireless ADB;
macOS host/Colima Docker, Python 3.13 FastAPI forwarding, pinned scrcpy 3.3.4 H.264,
React/WebCodecs/canvas over local HTTP. Existing telemetry collection remains active.
No input is injected to generate motion. These are mostly static-display measurements.

Configurations use maximum longest encoded edge, not conventional short-edge “p”
resolutions. Low: 480/15 FPS; medium: 720/30 FPS; high: 1080/30 FPS. UI targets
1/2/4 Mbit/s respectively; harness targets 1/3/6 Mbit/s. These are encoder ceilings,
not measured output bitrate. Backend supports only H.264 and uses no transcoding.

| Measurement | Definition and limitation |
| --- | --- |
| First decoded frame | Browser time from start request to first VideoDecoder output; includes negotiation/startup. Separate from server capture transport startup. |
| Received video FPS | Count framed video access units, excluding configuration, per observation time. Encoded frames received can differ from producer/capture FPS. |
| Decoded/rendered FPS | Successful VideoDecoder outputs synchronously drawn on canvas per interval. Does not prove compositor display refresh or motion-to-photon FPS. |
| Received WS bytes/sec | Binary WebSocket payload including 12-byte framing and SPS/configuration. Does not include TCP/WebSocket headers or retransmissions. |
| Video bitrate | Access-unit bytes/sec ×8 if payload-only counted; framed WebSocket throughput otherwise explicitly labeled. |
| Backend CPU/memory | Docker CPU%/container memory; backend `/proc/1` RSS and descriptors sampled separately. Container memory includes transient sampler overhead. |
| Browser CPU/memory | Chromium CDP page TaskDuration ratio estimates page CPU; JS heap does not include GPU/decoder native memory. Firefox/WebKit equivalent unavailable. |
| Capture FPS / end-to-end latency | Unavailable without source/instrumentation; do not equate configured FPS, packet cadence or decoder timing with these metrics. |

Actual browser and short live-run measurements are below. Long-soak completion was skipped at the user’s request.

Optimizations are limited to measured/observed lifecycle bottlenecks: quick restart
cleanup serialization, freeing terminal stream references and timers, codec-generation
guards, keyframe reset under decoder backlog, independent per-device control release,
correct geometry/gesture cancellation and precise drop counters. Shared encoding,
transcoding, WebRTC and broad performance rewrites were not introduced without evidence.
Two viewers still run two independent device encoders/tunnels; bandwidth/resource cost
must be considered before increasing configured limits.

## Measured browser playback

Final-source desktop observation windows include startup and approximately 12 seconds
of received/decoded output. All data comes from actual Samsung H.264. Rates are window
averages, not capture FPS. No user interaction generated motion.

| Engine | Quality / encoded size | First decoded frame (s) | Decoded outputs / window (FPS) | Framed WS bytes/s |
| --- | --- | --- | --- | --- |
| chromium | Low / 224×480 | 3.146 | 33/15.17s (2.18) | 1671.6 |
| chromium | Medium / 336×720 | 3.734 | 22/15.75s (1.40) | 2536.2 |
| chromium | High / 496×1080 | 3.607 | 33/15.62s (2.11) | 3781.1 |
| firefox | Low / 224×480 | 3.515 | 34/15.54s (2.19) | 1624.2 |
| firefox | Medium / 336×720 | 5.261 | 44/17.28s (2.55) | 2390.0 |
| firefox | High / 496×1080 | 3.693 | 33/15.71s (2.10) | 3744.9 |
| webkit | Low / 224×480 | 5.281 | 33/17.29s (1.91) | 1437.7 |
| webkit | Medium / 336×720 | 3.650 | 33/15.66s (2.11) | 2571.0 |
| webkit | High / 496×1080 | 3.763 | 11/15.77s (0.70) | 3667.1 |

Chromium page CPU estimates (CDP TaskDuration / wall time) and JS heaps:

| Quality | Page CPU estimate | JS heap bytes |
| --- | --- | --- |
| Low | 1.52% | 17,511,100 |
| Medium | 1.97% | 13,577,016 |
| High | 2.00% | 13,941,796 |

These page-task CPU estimates exclude GPU/native decoder CPU. Heap samples were not
forced-GC-normalized and do not establish long-term browser memory growth. Firefox and
WebKit equivalent CPU/native memory observations are unavailable. Desktop/mobile
emulation quality records are in [structured results](m6-results/browser-desktop-mobile.json).
Final desktop records are in [final-source results](m6-results/browser-final-desktop.json).

## Live transport and resource observations

Completed low-quality single-viewer smoke: **300.557 s**, **721 framed packets**,
**234,622 bytes**, **780.6 bytes/s** average framed WebSocket payload and first encoded
packet at **2.248 s**. Zero stream/reconnect failures; 23 healthy quiet intervals.
Configuration packets are included in this transport packet count; it is not a video
FPS or decoded frame count. [Structured result](m6-results/soak-single-five-minutes.json).

The user interrupted the intended 60-minute medium two-viewer run after **137.258 s
wall time from launch**, including baseline sampling. It produced **277,489 aggregate
framed WS bytes** before cleanup; individual per-viewer bandwidth and encoded frame
counts for that interrupted run are unavailable because its final export was cancelled.
Two simultaneous transport startups totaled **10.689 s** (mean **5.344 s**).
No controller, drops, stream/cleanup failures or capacity rejection was observed.
Two independent scrcpy captures/tunnels were active; sharing was not implemented.

Backend RSS samples during two viewers: **62,767,104–63,086,592 bytes**; after cleanup
**63,135,744 bytes**. The earliest and latest active samples differ by **319,488 bytes**
over ~70 s between samples. This short observation does not establish a long-term leak
bound or growth rate. Docker CPU samples were **39.42%** and **32.30%** of a CPU during
that interval, and **32.57%** after cleanup. They include ongoing monitoring/ADB workload
and transient sampler overhead; they do not isolate video-forwarding CPU. Open
backend descriptors sampled **31 then 27**, with **25** at immediate cleanup observation.
Device tunnels/manifest entries returned from **2 to 0**. Native browser/GPU memory,
true Android orphan process counts and motion-to-photon latency remain unavailable.
[Structured observations](m6-results/soak-interrupted.json).

The 15-/60-minute completion, scheduled live reconnect cycles, sustained decoded FPS
under motion, peak capture load and controlled resource scaling by viewer count remain
NOT RUN. Browser joins and leaves during the five-minute run exercised two concurrent
captures, but mixed quality/monitoring activity prevents attributing a CPU delta solely
to viewer count. No claims of linear resource scaling or long-duration certification.
