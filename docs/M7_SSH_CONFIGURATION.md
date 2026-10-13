# M7 SSH and Wireless Debugging configuration

M7 adds an optional SSH gateway. Android baseline management and ADB terminals do not
require SSH, root, an APK or a custom device agent. Install/configure Termux/OpenSSH or
another standard SSH server separately if desired; the dashboard never installs it.

## Enable access

ADB terminals default disabled. Set `ANDROID_FLEET_TERMINAL_ADB_ENABLED=true` only after
reviewing broad Android shell-user access. Administrators have `terminal:adb` and
`terminal:ssh`; operators receive neither by default. An administrator can explicitly
add these permissions to named operator records using the RBAC `permissions` array.
Viewers cannot receive terminal creation permissions. `terminal:view` permits viewing
one's own session metadata; it does not permit attaching to another user's session.
All terminal use requires authenticated identities. SSH profile management and privileged
session termination remain administrator permissions.

SSH defaults to no destinations. Set `ANDROID_FLEET_SSH_DESTINATIONS` to a JSON array of
exact `host:port` entries, for example `["android.example.internal:8022"]`. DNS resolution
is pinned at profile approval; changed addresses require editing the profile. Connections
use the pinned IP and pinned SSH key. Link-local/metadata, multicast, unspecified addresses
and ports 2375, 2376 and 5037 are rejected. Approve only trusted SSH servers; an approved
host is a powerful network trust decision. No SSH agent, local SSH config, implicit keys,
proxy commands or automatic unverified connection are supported.

Provide `ANDROID_FLEET_SSH_ENCRYPTION_KEY` from a separately managed private secret store.
Generate a Fernet key with Python's `cryptography.fernet.Fernet.generate_key()` in a private
administrator environment. Never commit keys, export them into public logs or keep the
only copy alongside SQLite. An empty setting permits the dashboard to start but profile
credential creation/use fails closed. Deployment passes the key as an environment secret;
users with Docker administration can inspect container environment and are trusted.

## Profiles, credentials and host keys

Open **SSH Connections**, create an approved host/port/username profile, choose private-key
or password authentication, and submit the credential once. Saved responses contain a
credential reference only. Editing without a credential preserves the encrypted existing
credential; supplying one replaces it. Encrypted private keys requiring passphrases are
not supported as a separate two-secret authentication mode; use a dedicated limited key.

Fetch the candidate SHA256 fingerprint, verify it through a trusted channel on the SSH
server, and type the exact fingerprint to approve. Fetching does not authenticate or
silently establish trust. Changed host keys fail until an administrator verifies and
approves replacement. **Test** allocates a short-lived SSH shell/PTY then closes it;
use only on approved servers. Explicit **Open terminal** starts a session. No automatic
privileged reconnection occurs after backend restart.

An empty identity ACL grants no non-administrator access. Grant only named identities
with `terminal:ssh`; an associated Android device also enforces device scope. Profile
disabling/deleting or ACL revocation ends access on subsequent input/output or periodic
session checks. Administrators manage profiles and can terminate sessions according to
scope. The browser receives neither stored credentials nor SSH private keys.

## Backup, recovery and rotation

Before migration or deployment, take a consistent SQLite backup using
`scripts/backup_databases.py` and verify integrity. Preserve `devices.sqlite3`,
`ssh.sqlite3`, `terminals.sqlite3`, monitoring/alerts/operations/audit databases and the
existing ADB credential volume. Back up ADB credentials privately without printing them.
Back up the SSH encryption key separately with restricted access. A database alone
cannot recover credentials without the exact matching key.

For rotation: stop the owning backend, back up `ssh.sqlite3` and the old key separately,
then use `ProfileService(path, old_key, destinations).rotate_encryption_key(new_key)`
in an isolated administrative Python maintenance process. The method reencrypts all
credentials atomically in SQLite. Replace the managed deployment key with the new key
and restart. Verify a profile, retain the rollback backup securely, then retire the old
key according to policy. Do not rotate live instances or reuse stale keys against the
rotated database. A wrong key fails closed; replace credentials only after recovering
or deliberately abandoning the original encrypted records.

## Add Android Device

Administrators manage approved targets in **Device management → Wireless Debugging network
access**. Add a private phone IP or a trusted private Wi-Fi CIDR, then pair immediately;
no container change or restart is needed. These approvals persist in `pairing.sqlite3` in
the existing data volume. CIDRs work for any RFC1918 IPv4 or IPv6 ULA deployment; examples
include `192.168.1.0/24`, `10.42.0.0/24` and `172.20.4.0/24`. Exact IPs also work. IPv4
ranges must be /16 or narrower, and IPv6 ULA ranges /48 or narrower. Public, loopback,
link-local, metadata and broad catch-all networks are rejected. Only ports 1024–65535 are
accepted. Add only networks trusted for device pairing because every address in an
approved range may be contacted.

`ANDROID_FLEET_PAIRING_ALLOWED_HOSTS` is optional and seeds the approved networks on the
first database initialization for automated or infrastructure-managed setups. Dashboard
changes thereafter are persistent and are not overwritten by environment values on restart.
Include `pairing.sqlite3` in SQLite backups; the existing database backup script discovers
all `.sqlite3` files automatically.

An administrator opens **Device management → Add Android Device**. Follow the Developer
Options and Wireless Debugging instructions; enter IP, pairing port and the current
six-digit code from **Pair device with pairing code**. ADB receives the code through
stdin, never argv. The browser clears it on success or failure and never saves it.
Successful pairing establishes persistent ADB trust, not a live connection.

Enter the separate connection port from the main Wireless Debugging page. Retry this
step without re-pairing if the connection port is closed, changed or the device is
unreachable. The backend verifies an online authorized transport and retrieves properties.
Assign a friendly name and register. Verification expires after five minutes or restart;
repeat connect/verify if necessary. Duplicate endpoints are rejected. When stable Android
serial properties are available, duplicate identity and wrong-device updates are rejected.
Devices without stable identity can update a port at the same approved IP only; reused
IP addresses cannot be conclusively distinguished without a stable identity.

Use **Reconnect / Update Port** on an existing Wireless Debugging registration after the
connection port changes. This preserves its UUID and history. ADB keys remain in the
existing `/home/fleet/.android` volume. No port 5037 is published. Physical pairing needs
explicit operator approval during acceptance; automated tests use fake devices.

Optional existing mDNS discovery remains disabled by default. The Android ADB Wi-Fi
protocol advertises `_adb-tls-pairing._tcp` and `_adb-tls-connect._tcp`; Docker/Colima
multicast reliability is unverified. M7's complete manual workflow does not depend on
multicast and does not change Colima networking.

## WebSocket troubleshooting and limits

Use the same-origin frontend proxy, a configured exact Origin and an authenticated REST
session/ticket. The ticket is single use, short lived, carried in a WebSocket subprotocol
rather than the URL. Reverse proxies must preserve Upgrade, Connection and Origin headers
and avoid logging the sensitive ticket subprotocol header. Current nginx already forwards
upgrades for `/api/`. Heartbeats prevent proxy inactivity closure; terminal input idle and
maximum lifetime still expire sessions. Production Uvicorn bounds client frames to 4096
bytes and eight queued frames. Large paste is split into validated frames by the UI.

Local HTTP is accepted only within the existing loopback boundary. Remote access requires
private HTTPS/WSS plus an appropriate trusted network/identity policy. M7 is not a public
production hardening certification. Session output and keystrokes are not persisted;
xterm keeps bounded output in memory while the tab exists. No output recording, file
transfer, forwarded SSH ports, shared terminal attachment or automatic privileged restart.

Reference: [AsyncSSH API](https://asyncssh.readthedocs.io/en/latest/api.html) and
[Android ADB Wi-Fi architecture](https://android.googlesource.com/platform/packages/modules/adb/+/HEAD/docs/dev/adb_wifi.md).
