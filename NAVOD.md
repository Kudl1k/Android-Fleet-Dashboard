# Návod: spuštění, testování a nasazení (školní projekt)

Centrální monitoring rootnutých Android telefonů bez aplikace na telefonu:

```
telefony (ADB přes TCP :5555, root přes Magisk)
   → android-manager (Python collector, :9000/metrics)
   → Prometheus (:9090, časové řady)
   → Grafana (:1900, dashboardy)      + React dashboard (:8088, správa zařízení)
```

Všechny porty poslouchají jen na `127.0.0.1` serveru. Z vlastního PC se na ně chodí SSH tunelem.

## 1. Vývojová VM (VirtualBox)

- Ubuntu Server 24.04, SSH přesměrované z hostitele na `127.0.0.1:2222`.
- Tunely na porty 1900, 8088, 9090 a 9000 stačí přidat do `~/.ssh/config` na hostiteli:

  ```
  Host fleet-vm
      HostName 127.0.0.1
      Port 2222
      User <uživatel>
      LocalForward 1900 127.0.0.1:1900
      LocalForward 8088 127.0.0.1:8088
      LocalForward 9090 127.0.0.1:9090
      LocalForward 9000 127.0.0.1:9000
  ```

- VirtualBox běžící přes Hyper-V (Windows s VBS): víc než 4 vCPU vedlo k zamrzání jádra
  (soft lockup). Když VM po zapnutí/vypnutí VPN ztratí internet, pomůže
  `VBoxManage controlvm <VM> setlinkstate1 off` a pak `on`.
- Projekt je ve VM v `~/Android-Fleet-Dashboard`. Je tam nainstalovaný Docker, Compose a `adb`.

## 2. Spuštění

```bash
cd ~/Android-Fleet-Dashboard
cp .env.example .env              # jednou; nastavit GRAFANA_ADMIN_PASSWORD a ANDROID_FLEET_CONTROL_TOKEN
docker compose build              # jen na vývojové VM, ne na školní
docker compose -f docker-compose.yml -f docker-compose.school.yml up -d --no-build
docker compose ps                 # 4 služby, manager a frontend "healthy"
```

`ANDROID_FLEET_FAKE_ADB=true` (výchozí) simuluje 4 telefony: rootnutý, nerootnutý, offline
a s poškozeným výstupem. Na žádný telefon se přitom nepřipojuje. `ANDROID_FLEET_MDNS=false`
zajistí, že aplikace nic v síti nehledá. Připojuje se jen na ručně zaregistrované IP.

## 3. Prohlížení (z Windows)

V terminálu nechte běžet `ssh fleet-vm` a v prohlížeči otevřete:

| Co | Adresa | Přihlášení |
|---|---|---|
| Grafana: přehled flotily a detail zařízení | http://localhost:1900 → Dashboards → Android Fleet | `admin` / `GRAFANA_ADMIN_PASSWORD` z `.env` |
| React dashboard: správa zařízení a alerty | http://localhost:8088 | `ANDROID_FLEET_CONTROL_TOKEN` z `.env` |
| Prometheus: surová data a dotazy | http://localhost:9090 | — |
| Export metrik | http://localhost:9000/metrics | — |

## 4. Testy

```bash
# všechny backend testy na Linuxu s Pythonem 3.13 + ruff + mypy (v kontejneru, nic se neinstaluje)
docker run --rm -v "$PWD:/repo" -w /repo/backend python:3.13-slim sh -c \
  'pip install -q -e ".[dev]" && pytest -q && ruff check . && ruff format --check . && mypy src'

# frontend
cd frontend && npm ci && npm test && npm run build
```

Tři testy streamování a terminálu (`test_m6_soak::test_slow_consumer_queue_is_bounded`,
`test_screen_sessions::test_offline_watchdog_stops_static_stream`, `test_terminal_integration`)
jsou citlivé na časování a při zátěži občas selžou. S monitoringem nesouvisí.

## 5. Test se skutečným telefonem (až po schválení)

1. Telefon připravit podle [device-setup/README.md](device-setup/README.md): ADB TCP,
   firewall, klíč serveru.
2. V `.env` nastavit `ANDROID_FLEET_FAKE_ADB=false` a `ANDROID_FLEET_SEED_FAKE_DEVICES=false`.
3. Telefon zaregistrovat v React dashboardu (typ `adb_tcp`, IP, port 5555).
4. Ověřit v Grafaně: všechny metriky, `Root = yes`, GPU, procesy. Pak restartovat telefon
   a vypnout Wi-Fi: zařízení přejde na offline a samo se vrátí.
5. Demo throttlingu: na telefonu `7z b` (Termux) → v detailu zařízení roste CPU a teplota,
   `CPU frequency limit` klesá pod `max`.

### Telefon přes USB, když Wi-Fi izoluje klienty

Na sítích s izolací klientů (domácí routery, hostovské sítě) se server k telefonu přes
Wi-Fi nedostane. Telefon pak zůstane na kabelu k Windows a backend ve VM se k němu
připojí přes tunel:

1. Na Windows stáhnout [Android platform-tools](https://developer.android.com/tools/releases/platform-tools)
   (stačí rozbalit do `%USERPROFILE%\tools\platform-tools`).
2. Na telefonu zapnout *Možnosti vývojáře → Ladění USB*, připojit kabel a potvrdit
   *Povolit ladění USB* (otisk klíče počítače).
3. Spustit `.\scripts\usb-bridge.ps1` a nechat ho běžet. Přepne adbd do TCP režimu a
   přesměruje `127.0.0.1:5555` na telefon; po restartu nebo přepojení telefonu to
   zopakuje sám.
4. V dashboardu zaregistrovat telefon jako `adb_tcp`, host `10.0.2.2`, port `5555`
   (`10.0.2.2` je z VirtualBox NAT adresa Windows). Na telefonu ještě jednou potvrdit
   klíč, tentokrát klíč backendu.

Ověřeno 25. 10. 2026 na Samsung Galaxy A14 (Android 14, bez rootu).

## 6. Nasazení na školní VM (po schválení vyučujícím)

Školní VM (Ubuntu 24.04, 2 vCPU, 1,4 GB RAM, **2,9 GB volného disku**, přístup přes školní VPN)
nemá Docker. Build se tam nedělá, image se posílají hotové:

```bash
# na školní VM jednou: Docker Engine + compose plugin (viz docs.docker.com/engine/install/ubuntu)
# z vývojové VM:
./deploy/school/ship_images.sh <uživatel>@<adresa-školní-VM>
# zkopírovat repozitář (bez node_modules), na školní VM:
docker compose -f docker-compose.yml -f docker-compose.school.yml up -d --no-build
```

Naměřeno ve fake režimu: celý stack zabírá ~160 MB RAM, takže **RAM stačí**. Image mají
~1,6 GB a Docker Engine ~0,5 GB, takže **disk bude těsný**. Prometheus má limit
400 MB / 30 dní.

## 7. Co je nového oproti původnímu stavu

| Oblast | Metriky / soubory |
|---|---|
| Identita zařízení | `android_device_info{manufacturer,model,android_version,soc,kernel}` |
| Využití rootu | ZRAM, GPU, procesy a thermal sysfs se čtou přes `su -c`; při selhání `su` bez rootu |
| ZRAM | `android_zram_*` |
| GPU (vendor backendy) | Qualcomm Adreno (`kgsl`), Arm Mali (Tensor/Exynos/MediaTek): `android_gpu_*` |
| Throttling | `android_cpu_max_frequency_hz`, `android_cpu_frequency_limit_hz`, `android_cpu_frequency_capped` |
| Procesy | `android_process_count`, top 5 `android_process_cpu_ratio` a `android_process_memory_bytes` |
| Kapacita baterie | `android_battery_charge_ampere_hours` (aktuální náboj), `..._charge_full_...` a `..._charge_full_design_...` (opotřebení), `android_battery_cycle_count` |
| Grafana | tabulka stavu celé flotily, teplota a capping v přehledu; v detailu info, GPU, throttling, ZRAM, procesy |
| Telefony | `device-setup/`: Magisk boot skript, firewall, autorizace klíče |
| React dashboard | nový vzhled „Lab bench“ (`DESIGN.md`), hromadné akce, Ctrl+K, notifikace alertů |
| Grafy | teploty seskupené podle typu, strop frekvence s vyznačeným throttlingem, synchronizovaný kurzor, decimace bodů |
| Program runs | stránka `/runs`: souhrn každého runu (CPU, RAM, teplota, throttling, baterie), porovnání dvou runů, export CSV |
| Nastavení | stránka `/settings`: interval sběru, kontroly spojení a alertů za běhu; interval sběru i pro jednotlivé zařízení |
| USB most | `scripts/usb-bridge.ps1` pro sítě s izolací klientů |
| Malá VM | `docker-compose.school.yml`, `deploy/school/ship_images.sh` |

Podrobnosti o metrikách jsou v [docs/METRICS.md](docs/METRICS.md).
