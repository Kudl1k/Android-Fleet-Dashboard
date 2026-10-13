Fleet and per-device dashboards belong to M3. M0 provisions only a Prometheus datasource.

M6 adds **Android Fleet Streaming** (`android-fleet-streaming`): active streams,
attached viewers, exclusive controllers, mean transport startup, WebSocket throughput,
actual encoded-video drops, failures, cleanup failures and capacity rejections. These
queries use aggregate metrics without session/user/device labels. Browser decoded FPS
and first decoded frame remain browser measurements; static displays need not reach
configured capture ceilings. See `docs/M6_OPERATIONS.md` and `docs/M6_PERFORMANCE.md`.
