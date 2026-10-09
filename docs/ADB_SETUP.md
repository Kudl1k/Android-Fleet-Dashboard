# ADB setup and first Pixel

No Android monitoring agent, management APK, Termux or SSH server is required. The backend never enables TCP debugging or changes phone configuration. Authorize the management ADB identity manually and keep Android RSA authentication enabled.

## macOS Docker/Colima default

Use the container-owned server with adb-keys persisted at /home/fleet/.android. Port 5037 is not published; device connections go outbound from the VM/container. Restarting the backend preserves RSA keys and Wireless Debugging trust records. The shipped image has an ADB CLI with TLS pairing support. Docker Desktop and Colima differ in host routing, USB and multicast; no host alias, privileged mode or host networking is assumed.

Host-managed ADB has better native USB/mDNS visibility but needs a separately secured path from the container to its unauthenticated server protocol. Do not bind adb -a to the LAN or publish 5037. ADB_SERVER_HOST/PORT are only for an operator-secured private server/tunnel whose routing has been tested. Container pairing trusts the container server; pairing an unrelated host server does not authorize this identity.

Compose and the adapter disable autonomous ADB mDNS reconnection with ADB_MDNS_AUTO_CONNECT=0; the manager owns reconnect intent. For an external already-running server, set this when starting that server too. Do not restart a shared external ADB server without coordinating with its other users. See [ADB source policy](https://android.googlesource.com/platform/system/core/+/5af3d723a7d5d5b8fdc4b26139d75730f3035f55/adb/client/transport_mdns.cpp).

## First non-rooted Pixel: Wireless Debugging

1. Put the Pixel and management host on a trusted network with outbound device reachability. Enable Developer Options and Wireless Debugging on the phone (supported Android versions).
2. Set ANDROID_FLEET_FAKE_ADB=false and a strong ANDROID_FLEET_CONTROL_TOKEN in .env. Preserve Grafana credentials and published ports. Generate a token locally with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`. Deploy only this project's backend when ready:

   ```bash
   docker-compose build android-manager
   docker-compose up -d --no-deps android-manager
   ```

3. On the phone choose Pair device with pairing code. Pair from the same container/server the backend uses:

   ```bash
   docker-compose exec android-manager adb pair PHONE_IP:PAIRING_PORT
   ```

   Enter the code interactively. It must not enter shell history, backend logs or the registry. The pairing port is separate from the connection port on the main Wireless Debugging screen.
4. Export the configured token locally as FLEET_CONTROL_TOKEN. Register using the **connection port**, substituting the phone's actual address:

   ```bash
   curl -fsS http://127.0.0.1:9000/api/v1/devices \
     -H "Authorization: Bearer $FLEET_CONTROL_TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"name":"My Pixel","connection_type":"wireless_adb","host":"192.168.1.150","port":37123}'
   ```

   The response assigns a stable UUID. Default auto_connect=true requests a bounded connection attempt and schedules retries. Inspect the returned state/error fields, then GET /api/v1/devices/DEVICE_ID. ONLINE requires an authorized ADB listing and successful read-only probing. Accept any phone authorization prompt. A refused port usually means the connection port changed; PATCH host/port while retaining the UUID.
5. To resume after intentional disconnect:

   ```bash
   curl -fsS -X POST http://127.0.0.1:9000/api/v1/devices/DEVICE_ID/connect \
     -H "Authorization: Bearer $FLEET_CONTROL_TOKEN"
   ```

   POST the corresponding /disconnect route to persist auto_connect=false. It survives restarts. It does not revoke RSA/TLS trust; revoke trust on the phone when required. Unplugging USB remains a separate physical action.

See [official ADB documentation](https://developer.android.com/tools/adb) and [Wireless Debugging architecture](https://android.googlesource.com/platform/packages/modules/adb/+/HEAD/docs/dev/adb_wifi.md). Pairing must be performed again if trust is revoked; no API accepts pairing secrets.

## Optional discovery and dynamic ports

ANDROID_FLEET_MDNS=true enables best-effort `adb mdns services` alongside normal device listing. GET /api/v1/discovery/devices displays unregistered transports and advertisements. Use an exact connect instance (for example adb-DEVICE-GUID._adb-tls-connect._tcp) as mdns_service on a wireless registration; host/port remain mandatory fallback fields. The backend associates no device merely because two services share a host.

Pairing advertisements are displayed as PAIRING_REQUIRED and never used as connect endpoints. Dynamic connection ports can be refreshed from matching connect advertisements while mDNS is available. If multicast is unavailable, keep the manual port current. The last working discovered endpoint is retained only in runtime memory; after restart the configured fallback is used. Discovery neither registers nor pairs a device automatically.

`docker-compose exec android-manager adb mdns services` can diagnose what this server sees. Empty discovery is expected on some bridged networks and is not a reason to open 5037 or disable authentication.

## Rooted TCP devices

Use a fixed IP/DHCP reservation and an operator-configured authenticated ADB TCP port such as 5555. Register connection_type=adb_tcp with host and port through the same endpoint. Restrict device ADB access to the management host with firewall rules; never expose 5555 publicly. Authorize this ADB identity on the device. Root is independently detected with bounded `id -u` / `su -c 'id -u'` observations; TCP does not imply root. Preauthorize root prompts under supervision.

Magisk/KernelSU/APatch boot persistence is separate device-side setup; there is no universal fleet recipe. Never disable ro.adb.secure or automatically enable TCP debugging from the backend.

## USB and limitations

Native development can register USB devices by exact serial. Linux containers need explicit USB mappings/udev permissions; macOS Docker Desktop, Colima and Windows involve VM routing and do not accept a universal /dev/bus/usb recipe. This stack is network-first and does not configure USB passthrough. A manager USB disconnect disables monitoring/reconnect intent without detaching the physical USB transport.

No actual Android device was tested during M1 implementation. Pairing, hardware authorization and multicast visibility must be verified on the intended fleet/network. Protect ADB keys and database backups; do not commit them.

## Monitoring acceptance and dynamic ports

Wireless Debugging connection ports can change whenever debugging is toggled or its service restarts. A paired key remains trusted, but the saved endpoint can become unreachable. Update the existing registration's `port` with authenticated PATCH instead of creating a new device; this preserves its stable ID and historical series. Pairing ports are separate. Keep Wireless Debugging enabled throughout acceptance. M2 monitoring uses read-only baseline sources without `su`; optional denied sources simply disappear. A friendly device name is not hardware identity: inspect the probed model/version before reporting acceptance as a Pixel test.
