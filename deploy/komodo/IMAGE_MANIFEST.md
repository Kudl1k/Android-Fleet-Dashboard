# Published image manifest

Build execution: 2026-10-10; Docker context `colima`; platform `linux/arm64`.

Git HEAD: `2ba42d3affcab3241667236789c901d323f4f18a`. Working tree was dirty before this work: images include existing uncommitted application changes. No commit was created. Cached Dockerfile layers were reused; layer creation dates below precede the build execution. Use digest pins, not mutable tags.

| Image | Tag | Digest | Architecture | Image creation date | Registry verification |
|---|---|---|---|---|---|
| mac.lab:5000/android-fleet/backend | 2ba42d3 | `sha256:f96f8665ca686db4f1a89ee350601f0ad1114d4da075da1746eb5795ca7aef46` | linux/arm64 | 2026-10-10T19:50:39.985407791+02:00 | PASS HTTP manifest + config blob, digest SHA256 verified |
| mac.lab:5000/android-fleet/backend | latest | `sha256:f96f8665ca686db4f1a89ee350601f0ad1114d4da075da1746eb5795ca7aef46` | linux/arm64 | 2026-10-10T19:50:39.985407791+02:00 | PASS HTTP manifest + config blob, digest SHA256 verified |
| mac.lab:5000/android-fleet/frontend | 2ba42d3 | `sha256:5ac714b30cc89002342818c2da0380f30c9bac0b058c6a7ef1afc1db5bff8c5c` | linux/arm64 | 2026-10-10T19:44:08.411090499+02:00 | PASS HTTP manifest + config blob, digest SHA256 verified |
| mac.lab:5000/android-fleet/frontend | latest | `sha256:5ac714b30cc89002342818c2da0380f30c9bac0b058c6a7ef1afc1db5bff8c5c` | linux/arm64 | 2026-10-10T19:44:08.411090499+02:00 | PASS HTTP manifest + config blob, digest SHA256 verified |

Publication transport: successful Docker pushes via `192.168.123.238:5000`, the already-trusted alias of the same registry. All four manifests were retrieved through `http://mac.lab:5000` and their bytes hashed; config blobs confirm ARM64. Digest pulls via the IP succeeded. Direct Docker pushes/pulls through `mac.lab:5000` FAILED because the HTTP registry hostname is not trusted. User declined daemon configuration changes. No hostname-native successful push is claimed.

Backend runs as fleet UID 10001; frontend as UID 101. Backend installs project dependencies and ADB, includes checksum-pinned scrcpy server 3.3.4 and license. Monitoring image versions remain `prom/prometheus:v3.2.1` and `grafana/grafana:11.6.0`.

## M7 local preparation

Final-source backend/frontend images are prepared locally with m7-20261010 tags.
[M7 local manifest](M7_IMAGE_MANIFEST.json) records image IDs only; registry digests are
null because these images have not been pushed. Production image variables are unchanged.
