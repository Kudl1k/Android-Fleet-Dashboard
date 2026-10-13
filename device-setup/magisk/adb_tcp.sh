#!/system/bin/sh
# Magisk boot script: /data/adb/service.d/adb_tcp.sh (mode 0755, owner root).
#
# Re-enables authenticated ADB over TCP after every boot and restricts the ADB
# port to the central monitoring server. ADB RSA authentication stays enabled
# (ro.adb.secure is untouched); only keys in /data/misc/adb/adb_keys can connect.

ADB_PORT=5555
# Only this address may reach the ADB port. setup_device.sh replaces the value.
SERVER_IP=__SERVER_IP__

until [ "$(getprop sys.boot_completed)" = "1" ]; do sleep 5; done
# Wi-Fi is usually up a few seconds after boot_completed.
sleep 10

# Firewall: a dedicated chain keeps the rules idempotent across reruns.
iptables -N adb_guard 2>/dev/null
iptables -F adb_guard
iptables -A adb_guard -i lo -j RETURN
iptables -A adb_guard -s "$SERVER_IP" -j RETURN
iptables -A adb_guard -j DROP
iptables -C INPUT -p tcp --dport "$ADB_PORT" -j adb_guard 2>/dev/null \
  || iptables -I INPUT -p tcp --dport "$ADB_PORT" -j adb_guard
# The server reaches phones over IPv4; ADB over IPv6 is closed entirely.
ip6tables -C INPUT -p tcp --dport "$ADB_PORT" -j DROP 2>/dev/null \
  || ip6tables -I INPUT -p tcp --dport "$ADB_PORT" -j DROP

setprop service.adb.tcp.port "$ADB_PORT"
stop adbd
start adbd
log -t adb_tcp "ADB TCP $ADB_PORT enabled for $SERVER_IP"
