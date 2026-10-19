#!/bin/sh
# One-time preparation of a rooted (Magisk) phone for central ADB monitoring.
#
#   ./setup_device.sh adb:<serial>             <server-ip> <server-adbkey.pub>
#   ./setup_device.sh ssh:<user>@<host>[:port] <server-ip> <server-adbkey.pub>
#
# adb: the phone is already visible to `adb` (USB or an existing connection).
# ssh: the phone runs an SSH server, e.g. Termux sshd on port 8022 (lab setup).
#
# It installs the Magisk boot script, authorizes the monitoring server's ADB key,
# lets the ADB shell use su silently (no toast on every metric poll) and enables
# ADB over TCP immediately. Nothing is installed as an Android app.
set -eu

if [ "$#" -ne 3 ]; then
  sed -n '4,5p' "$0" >&2
  exit 2
fi
TARGET=$1
SERVER_IP=$2
PUBKEY=$3
HERE=$(cd "$(dirname "$0")" && pwd)

case "$SERVER_IP" in
  *[!0-9.]*|'') echo "server-ip must be an IPv4 address" >&2; exit 2 ;;
esac
[ -s "$PUBKEY" ] || { echo "missing public key: $PUBKEY" >&2; exit 2; }

# Termux's PATH does not contain Magisk's su; probe the usual locations.
FIND_SU='for s in su /product/bin/su /system/bin/su /system/xbin/su /debug_ramdisk/su /sbin/su; do command -v $s >/dev/null 2>&1 && { echo $s; exit 0; }; done; exit 1'

case "$TARGET" in
  adb:*)
    SERIAL=${TARGET#adb:}
    remote() { adb -s "$SERIAL" shell "$1"; }
    upload() { adb -s "$SERIAL" push "$1" "$2" >/dev/null; }
    STAGE=/data/local/tmp
    ;;
  ssh:*)
    DEST=${TARGET#ssh:}
    PORT=22
    case "$DEST" in *:*) PORT=${DEST##*:}; DEST=${DEST%:*} ;; esac
    remote() { ssh -p "$PORT" "$DEST" "$1"; }
    upload() { scp -q -P "$PORT" "$1" "$DEST:$2"; }
    STAGE=$(remote 'echo $HOME' | tr -d '\r')
    ;;
  *) echo "target must start with adb: or ssh:" >&2; exit 2 ;;
esac

SU=$(remote "$FIND_SU" | tr -d '\r' || true)
[ -n "$SU" ] || { echo "su not found on the phone" >&2; exit 1; }
as_root() { remote "$SU -c '$1'"; }

echo "== root check ($SU)"
[ "$(as_root 'id -u' | tr -d '\r')" = "0" ] || {
  echo "su was denied: allow root in the Magisk app and rerun" >&2
  exit 1
}

echo "== Magisk policy: ADB shell (uid 2000) may use su without notifications"
as_root "magisk --sqlite \"REPLACE INTO policies (uid,policy,until,logging,notification) VALUES(2000,2,0,0,0)\""

echo "== boot script"
TMP=$(mktemp)
sed "s/__SERVER_IP__/$SERVER_IP/" "$HERE/magisk/adb_tcp.sh" > "$TMP"
upload "$TMP" "$STAGE/adb_tcp.sh"
rm -f "$TMP"
as_root "mkdir -p /data/adb/service.d && cp $STAGE/adb_tcp.sh /data/adb/service.d/adb_tcp.sh && rm $STAGE/adb_tcp.sh && chown 0:0 /data/adb/service.d/adb_tcp.sh && chmod 0755 /data/adb/service.d/adb_tcp.sh"

echo "== authorize server ADB key"
upload "$PUBKEY" "$STAGE/server_adbkey.pub"
as_root "touch /data/misc/adb/adb_keys && (grep -qxF -f $STAGE/server_adbkey.pub /data/misc/adb/adb_keys || cat $STAGE/server_adbkey.pub >> /data/misc/adb/adb_keys) && chown system:shell /data/misc/adb/adb_keys && chmod 0640 /data/misc/adb/adb_keys && rm $STAGE/server_adbkey.pub"

echo "== enable now (the boot script handles later restarts)"
as_root "nohup sh /data/adb/service.d/adb_tcp.sh >/dev/null 2>&1 &"
echo "done: within ~15 s the phone accepts ADB on port 5555 from $SERVER_IP only"
