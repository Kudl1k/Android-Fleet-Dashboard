# Příprava telefonů

Na telefon se neinstaluje žádná aplikace. Potřebuje jen root přes Magisk a jednorázovou
konfiguraci, kterou udělá `setup_device.sh`:

1. **Magisk boot skript** `/data/adb/service.d/adb_tcp.sh`: po každém startu zapne ADB
   přes TCP na portu 5555 a firewallem (`iptables`, vlastní řetězec `adb_guard`) povolí
   port 5555 jen z IP centrálního serveru. IPv6 přístup na 5555 zakáže úplně.
2. **Autorizace ADB klíče serveru**: veřejný klíč z kontejneru se přidá do
   `/data/misc/adb/adb_keys`, takže se na telefonu nemusí nic potvrzovat. ADB RSA
   autentizace zůstává zapnutá (`ro.adb.secure` se nemění).
3. **Magisk politika pro ADB shell (uid 2000)**: povolí `su` bez notifikace. Collector
   volá `su` každých 30 s a bez toho by telefon neustále ukazoval toast.
4. **Okamžité zapnutí** ADB TCP, bez restartu.

## Požadavky

- Rootnutý telefon s Magiskem.
- **Pevná IP telefonu** (DHCP rezervace na routeru). Telefony v laboratoři zatím IP mění.
- Veřejný ADB klíč serveru. ADB server v kontejneru ho vytvoří při prvním spuštění a uloží
  do volume `adb-keys`, takže přežije restart i rebuild:

  ```bash
  docker compose exec android-manager adb devices    # spustí ADB server, vytvoří klíč
  docker compose exec android-manager cat /home/fleet/.android/adbkey.pub > server_adbkey.pub
  ```

## Spuštění

Telefon dostupný přes ADB (USB kabel nebo existující spojení):

```bash
./device-setup/setup_device.sh adb:<serial> <IP-serveru> server_adbkey.pub
```

Telefon s Termux SSH (stav v laboratoři, port 8022). Skript se zeptá na heslo Termuxu
a při prvním `su` je potřeba v Magisku na telefonu povolit root pro Termux:

```bash
./device-setup/setup_device.sh ssh:<termux-uživatel>@<IP-telefonu>:8022 <IP-serveru> server_adbkey.pub
```

`<IP-serveru>` je LAN adresa centrálního serveru (školní VM), jediná adresa, které firewall
telefonu povolí port 5555. Termux uživatele zjistíte v Termuxu příkazem `whoami`. Skript se
musí spouštět ze stroje, který na telefon
vidí, tedy ze školní VM.

Pak telefon zaregistrujte v dashboardu (Device management → typ `adb_tcp`, IP, port 5555),
nebo přes API `POST /api/v1/devices`.

## Ověření a vrácení změn

```bash
adb connect <IP-telefonu>:5555 && adb -s <IP-telefonu>:5555 shell su -c id   # z serveru
```

Vrácení na telefonu (jako root):

```sh
rm /data/adb/service.d/adb_tcp.sh
iptables -D INPUT -p tcp --dport 5555 -j adb_guard; iptables -F adb_guard; iptables -X adb_guard
ip6tables -D INPUT -p tcp --dport 5555 -j DROP
setprop service.adb.tcp.port -1; stop adbd; start adbd
```

Klíč serveru z `/data/misc/adb/adb_keys` odstraníte editací souboru, nebo v Nastavení →
Možnosti pro vývojáře → Zrušit autorizace ladění USB.

> Stav: skripty jsou zkontrolované jen syntakticky. Na skutečném telefonu ještě neběžely.
