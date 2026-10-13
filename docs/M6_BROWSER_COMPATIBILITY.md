# M6 browser compatibility

WebCodecs availability and H.264 support are probed at runtime; codec negotiation uses
the actual device SPS profile. No software decoder, transcoder, MSE or WebRTC fallback
is introduced. Unsupported secure context/WebCodecs and unsupported H.264 configurations
produce clear errors; the user can stop and use a supported browser.

Acceptance uses Playwright desktop engines on macOS and localhost. Mobile results are
viewport/touch emulation, not actual mobile Safari/Android Chrome hardware. Playwright
WebKit is an engine build and does not certify the shipping Safari application.

| Engine | Version | Feature probe | Actual Samsung decode | Lifecycle/fullscreen/resizing |
| --- | --- | --- | --- | --- |
| Chromium | 156.0.8078.4 | PASS | PASS (desktop/mobile emulation) | PASS (desktop/mobile emulation) |
| Firefox | 157.0 | PASS | PASS (desktop/mobile emulation) | PASS (desktop/mobile emulation) |
| Playwright WebKit | 27.2 | PASS | PASS (desktop/mobile emulation) | PASS (desktop/mobile emulation) |
| Shipping Safari | — | NOT RUN | NOT RUN | NOT RUN |
| Actual mobile browsers | — | NOT RUN | NOT RUN | NOT RUN |

All available engines report a secure context, VideoDecoder, H.264 `avc1.64001f`,
2D canvas and fullscreen capability. This alone is not playback acceptance.

Automated frontend fixtures validate unsupported profile errors, absent WebCodecs,
closed decoder cleanup, async configuration races, bounded backlog/keyframe recovery,
portrait/landscape decoded dimensions, coordinate mapping/letterboxing, window/fullscreen
handling, input focus and reconnect authorization. On tab suspension playback stops
and the session releases resources; restarting requires explicit view-only start and
control acquisition remains separate.

Live acceptance receives tickets/video/heartbeats only. It does not click the canvas,
acquire control or press Android navigation. Physical rotation/input remain pending.

Final-source desktop rerun passed all three qualities in all three engines, including
fullscreen enter/exit, viewport resizing, WebSocket disconnect/restart and route cleanup.
Each engine created/closed five decoder instances with no page errors. Earlier matched
desktop/mobile runs created/closed five decoders per viewport. Instruments observed
only ticket/ping messages, never physical input. See [final-source results](m6-results/browser-final-desktop.json)
and [desktop/mobile results](m6-results/browser-desktop-mobile.json).
