#!/usr/bin/env bash
#
# provision_panel.sh -- take a plugged-in Pico W from "whatever's on it" to a registered,
# driving, verified rlab-camera illumination panel, in one shot. Run ON THE PI, over SSH,
# with exactly one board plugged into a Pi USB port directly (NOT a hub).
#
#   cd ~/rlab-camera
#   sudo panel_firmware/tools/provision_panel.sh              # auto-name (rlab-panel)
#   sudo panel_firmware/tools/provision_panel.sh rlab-panel-b # explicit advertised name
#
# It handles a board arriving as a blank RP2 bootloader, CircuitPython (the lab's old
# code.py world), or already-MicroPython: it flashes the MicroPython Pico W firmware,
# installs aioble, pushes hub75.py + main.py (with a unique advertised name), reads the
# board's BLE MAC, verifies it renders, and registers the address in RLAB_PANELS.
#
# sudo is required only to mount the RPI-RP2 bootloader volume and to restart the service.
# The script is idempotent: re-running against an already-provisioned board is safe, and
# re-registering an address already in RLAB_PANELS is a no-op.
#
# See panel_firmware/README.md for the manual equivalent and hardware/power notes.

set -euo pipefail

# --- configuration (override via env) ---------------------------------------------------
SERIAL="${SERIAL:-/dev/ttyACM0}"
SERVICE_USER="${SERVICE_USER:-rlab-camera}"
SERVICE_NAME="${SERVICE_NAME:-rlab-camera}"
UNIT_INSTALLED="${UNIT_INSTALLED:-/etc/systemd/system/rlab-camera.service}"
# Pico W (CYW43 radio) MicroPython build -- MUST be the "W" build or BLE won't work.
MICROPYTHON_UF2_URL="${MICROPYTHON_UF2_URL:-https://micropython.org/resources/firmware/RPI_PICO_W-20241129-v1.24.1.uf2}"
MICROPYLIB_REPO="${MICROPYLIB_REPO:-https://github.com/micropython/micropython-lib}"
# A board already running MicroPython is kept as-is (fast, and avoids depending on the UF2
# URL). Blank/CircuitPython boards always get the UF2. FORCE_REFLASH=1 reflashes regardless.
FORCE_REFLASH="${FORCE_REFLASH:-0}"

# --- paths derived from this script's location (sudo makes ~ = /root, so never use ~) ----
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
FW_DIR="$REPO_ROOT/panel_firmware/micropython"
UNIT_REPO="$REPO_ROOT/deploy/rlab-camera.service"
USER_HOME="$(getent passwd "$SERVICE_USER" | cut -d: -f6)"
MPREMOTE="${MPREMOTE:-$USER_HOME/mpremote-venv/bin/mpremote}"
VENV_PY="${VENV_PY:-$REPO_ROOT/.venv/bin/python}"
STAGING="${STAGING:-$USER_HOME/panel_flash}"

# --- output helpers ---------------------------------------------------------------------
if [ -t 1 ]; then B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; Z=$'\033[0m'
else B=""; G=""; Y=""; R=""; Z=""; fi
step() { printf '\n%s==> %s%s\n' "$B" "$*" "$Z"; }
info() { printf '    %s\n' "$*"; }
ok()   { printf '    %s%s%s\n' "$G" "$*" "$Z"; }
warn() { printf '    %s%s%s\n' "$Y" "$*" "$Z" >&2; }
die()  { printf '\n%sERROR: %s%s\n' "$R" "$*" "$Z" >&2; exit 1; }

# Run mpremote / venv python as the service user (matches the tested dialout + bluez setup).
as_user() { sudo -u "$SERVICE_USER" "$@"; }
mp()      { as_user "$MPREMOTE" connect "$SERIAL" "$@"; }

# A mid-run serial drop almost always means the board browned out -- explain instead of
# dumping a raw mpremote traceback.
POWER_HINT="The board likely lost power (brownout). Give the LED matrix its OWN external 5V
    supply, plug the Pico into a Pi USB port DIRECTLY (not a hub), and re-run. See
    panel_firmware/README.md (Power)."
on_err() {
  local code=$?
  printf '\n%sProvisioning failed (exit %d) at line %d.%s\n' "$R" "$code" "${BASH_LINENO[0]}" "$Z" >&2
  if [ -n "$SERIAL" ] && [ ! -e "$SERIAL" ]; then
    warn "$SERIAL is gone."
    warn "$POWER_HINT"
  fi
  exit "$code"
}
trap on_err ERR

# --- args -------------------------------------------------------------------------------
PANEL_NAME="${1:-rlab-panel}"
if ! [[ "$PANEL_NAME" =~ ^[A-Za-z0-9_-]+$ ]]; then
  die "panel name '$PANEL_NAME' must be letters, digits, '-' or '_' (it is a BLE adv name)."
fi

# ========================================================================================
step "Stage 1/8: preflight"
[ "$(id -u)" -eq 0 ] || die "run with sudo (mounting RPI-RP2 and restarting the service need root)."
[ -n "$USER_HOME" ] || die "user '$SERVICE_USER' not found."
[ -x "$MPREMOTE" ] || die "mpremote not found at $MPREMOTE (expected in $SERVICE_USER's mpremote-venv)."
[ -x "$VENV_PY" ]  || die "app venv python not found at $VENV_PY."
for f in "$FW_DIR/hub75.py" "$FW_DIR/main.py"; do
  [ -f "$f" ] || die "firmware file missing: $f"
done
as_user mkdir -p "$STAGING"
info "repo:      $REPO_ROOT"
info "panel name: $PANEL_NAME"
info "serial:    $SERIAL"
ok "preflight passed."

# --- helpers used across stages ---------------------------------------------------------
rpi_rp2_dev() { blkid -L RPI-RP2 2>/dev/null || true; }
serial_present() { [ -e "$SERIAL" ]; }

# Is the board currently running MicroPython? (Quietly; a non-MP or absent board -> no.)
is_micropython() {
  serial_present || return 1
  local impl
  impl="$(as_user "$MPREMOTE" connect "$SERIAL" exec \
            'import sys; print(sys.implementation.name)' 2>/dev/null || true)"
  [ "$impl" = "micropython" ]
}

wait_for_bootloader() {  # poll for the RPI-RP2 volume, with a manual fallback
  local dev
  for _ in $(seq 1 20); do
    dev="$(rpi_rp2_dev)"; [ -n "$dev" ] && { echo "$dev"; return 0; }
    sleep 1
  done
  warn "RPI-RP2 didn't appear automatically."
  info "Put the board into bootloader mode by hand: hold BOOTSET, tap RUN, release BOOTSET."
  read -r -p "    Press Enter once done (or Ctrl-C to abort)... " _
  for _ in $(seq 1 30); do
    dev="$(rpi_rp2_dev)"; [ -n "$dev" ] && { echo "$dev"; return 0; }
    sleep 1
  done
  die "still no RPI-RP2 volume; check the cable/power and try again."
}

# ========================================================================================
step "Stage 2/8: detect board state"
ALREADY_MP=0
if [ -n "$(rpi_rp2_dev)" ]; then
  info "board is already in the RP2 bootloader."
elif is_micropython; then
  ALREADY_MP=1
  if [ "$FORCE_REFLASH" = "1" ]; then
    info "board runs MicroPython; FORCE_REFLASH=1 -> dropping to the bootloader to reflash."
    mp bootloader 2>/dev/null || true
    wait_for_bootloader >/dev/null
  else
    ok "board already runs MicroPython; keeping it (set FORCE_REFLASH=1 to reflash)."
  fi
else
  # CircuitPython or unknown. Best-effort auto-entry via the CircuitPython REPL, then fall
  # back to the manual BOOTSET/RUN prompt (wait_for_bootloader) which works for any state.
  if serial_present; then
    info "board is not MicroPython (CircuitPython/unknown); attempting REPL bootloader entry."
    { stty -F "$SERIAL" raw -echo 115200 2>/dev/null &&
      printf '\x03\x03' > "$SERIAL" 2>/dev/null && sleep 0.4 &&
      printf 'import microcontroller\r\n' > "$SERIAL" 2>/dev/null &&
      printf 'microcontroller.on_next_reset(microcontroller.RunMode.BOOTLOADER)\r\n' > "$SERIAL" 2>/dev/null &&
      printf 'microcontroller.reset()\r\n' > "$SERIAL" 2>/dev/null; } || true
  else
    info "no serial device at $SERIAL; will prompt for manual bootloader entry."
  fi
  wait_for_bootloader >/dev/null
fi

# ========================================================================================
step "Stage 3/8: install MicroPython"
if [ "$ALREADY_MP" = "1" ] && [ "$FORCE_REFLASH" != "1" ]; then
  ok "skipped (keeping existing MicroPython)."
else
  DEV="$(rpi_rp2_dev)" || true
  [ -n "$DEV" ] || DEV="$(wait_for_bootloader)"
  UF2="$STAGING/$(basename "$MICROPYTHON_UF2_URL")"
  if [ ! -f "$UF2" ]; then
    info "downloading $MICROPYTHON_UF2_URL"
    as_user curl -fL "$MICROPYTHON_UF2_URL" -o "$UF2" || die "UF2 download failed."
  else
    info "using cached $UF2"
  fi
  MNT="$(mktemp -d)"
  mount "$DEV" "$MNT" || die "could not mount RPI-RP2 ($DEV)."
  info "flashing UF2 onto the board..."
  # Copying the UF2 triggers the flash + reboot; the volume vanishes mid-copy, so tolerate
  # the write/sync/umount erroring out as the device disappears.
  cp "$UF2" "$MNT/" 2>/dev/null || true
  sync 2>/dev/null || true
  umount "$MNT" 2>/dev/null || true
  rmdir "$MNT" 2>/dev/null || true
  info "waiting for the board to reboot into MicroPython..."
  booted=0
  for _ in $(seq 1 30); do
    if is_micropython; then booted=1; break; fi
    sleep 1
  done
  [ "$booted" = "1" ] || die "board didn't come back as MicroPython on $SERIAL. $POWER_HINT"
  ok "MicroPython is running."
fi

# ========================================================================================
step "Stage 4/8: install aioble"
LIBDIR="$STAGING/micropython-lib"
if [ -d "$LIBDIR/.git" ]; then
  info "updating cached micropython-lib..."
  as_user git -C "$LIBDIR" pull --ff-only --quiet || warn "git pull failed; using cached copy."
else
  info "cloning micropython-lib (shallow)..."
  as_user git clone --depth 1 "$MICROPYLIB_REPO" "$LIBDIR" || die "git clone failed."
fi
AIOBLE_PKG="$LIBDIR/micropython/bluetooth/aioble/aioble"
[ -d "$AIOBLE_PKG" ] || die "aioble package not found at $AIOBLE_PKG (repo layout changed?)."
info "copying aioble to the board..."
mp fs cp -r "$AIOBLE_PKG" : || die "pushing aioble failed. $POWER_HINT"
ok "aioble installed."

# ========================================================================================
step "Stage 5/8: push firmware (advertised name: $PANEL_NAME)"
TMP_MAIN="$(mktemp --suffix=.py)"
trap 'rm -f "$TMP_MAIN"' EXIT
# Rewrite _PANEL_NAME so multiple panels stay distinguishable at the bench.
sed -E "s/^_PANEL_NAME = \".*\"/_PANEL_NAME = \"$PANEL_NAME\"/" "$FW_DIR/main.py" > "$TMP_MAIN"
grep -q "^_PANEL_NAME = \"$PANEL_NAME\"" "$TMP_MAIN" || die "failed to set _PANEL_NAME in main.py."
chmod a+r "$TMP_MAIN"
mp fs cp "$FW_DIR/hub75.py" :hub75.py || die "pushing hub75.py failed. $POWER_HINT"
mp fs cp "$TMP_MAIN" :main.py         || die "pushing main.py failed. $POWER_HINT"
ok "firmware pushed."

# ========================================================================================
step "Stage 6/8: discover the panel's BLE address"
# Primary: read the MAC straight off the board over serial -- unambiguous even when other
# panels are already advertising. Must run BEFORE launching main.py (which then owns the
# BLE stack and blocks the REPL).
ADDR="$(mp exec 'import bluetooth, ubinascii
b = bluetooth.BLE(); b.active(1)
print(ubinascii.hexlify(b.config("mac")[1], ":").decode())' 2>/dev/null | tr -d '\r' | tail -n1 || true)"
if [[ "$ADDR" =~ ^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$ ]]; then
  ADDR="$(echo "$ADDR" | tr 'A-F' 'a-f')"
  ok "board reports BLE address $ADDR"
else
  warn "couldn't read the MAC over serial; will fall back to a BLE scan after launch."
  ADDR=""
fi

# ========================================================================================
step "Stage 7/8: launch and verify"
info "resetting the board to launch main.py..."
mp reset || die "reset failed. $POWER_HINT"
sleep 3  # let it advertise

if [ -z "$ADDR" ]; then
  info "scanning for an advertising rlab panel..."
  ADDR="$(cd "$REPO_ROOT" && as_user "$VENV_PY" - <<'PY' 2>/dev/null | tr -d '\r' | tail -n1 || true
import asyncio
from app.illumination.protocol import SERVICE_UUID
from bleak import BleakScanner
async def main():
    devs = await BleakScanner.discover(timeout=10.0, service_uuids=[SERVICE_UUID])
    if devs:
        print(devs[0].address.lower())
asyncio.run(main())
PY
)"
  [[ "$ADDR" =~ ^([0-9a-f]{2}:){5}[0-9a-f]{2}$ ]] || die "no rlab panel found by scan; check power/BLE."
  ok "scan found $ADDR"
fi

info "driving the panel (white/blue/red/green/off) via panel_probe..."
if (cd "$REPO_ROOT" && as_user "$VENV_PY" panel_firmware/tools/panel_probe.py "$ADDR"); then
  ok "panel responded to the full colour sequence."
else
  die "panel_probe could not drive $ADDR. Re-check power/wiring, then re-run."
fi

# ========================================================================================
step "Stage 8/8: register the panel"
add_addr_to_unit() {  # $1 = unit path; append $ADDR to the RLAB_PANELS= line if absent
  local unit="$1"
  [ -f "$unit" ] || { warn "unit not found: $unit (skipping)"; return 0; }
  local line cur
  line="$(grep -n '^Environment=RLAB_PANELS=' "$unit" | head -n1 || true)"
  [ -n "$line" ] || { warn "no RLAB_PANELS line in $unit (skipping)"; return 0; }
  cur="$(echo "$line" | sed -E 's/^[0-9]+:Environment=RLAB_PANELS=//')"
  case ",$cur," in
    *",$ADDR,"*) info "$unit already lists $ADDR."; return 0 ;;
  esac
  local new
  if [ -z "$cur" ]; then new="$ADDR"; else new="$cur,$ADDR"; fi
  sed -i -E "s|^Environment=RLAB_PANELS=.*|Environment=RLAB_PANELS=$new|" "$unit"
  ok "updated $unit -> RLAB_PANELS=$new"
}

info "discovered panel address: $ADDR"
printf '    %sRegister it in RLAB_PANELS and restart %s now?%s [y/N] ' "$B" "$SERVICE_NAME" "$Z"
read -r reply
if [[ "$reply" =~ ^[Yy] ]]; then
  add_addr_to_unit "$UNIT_INSTALLED"
  add_addr_to_unit "$UNIT_REPO"
  systemctl daemon-reload
  systemctl restart "$SERVICE_NAME"
  sleep 2
  ok "$SERVICE_NAME restarted."
  info "illumination status:"
  curl -s localhost:8000/api/illumination/status || warn "status query failed (is the app up?)"
  echo
else
  warn "not registered. To add it later:"
  info "  sudo sed -i -E 's|^Environment=RLAB_PANELS=(.*)|Environment=RLAB_PANELS=\\1,$ADDR|' $UNIT_INSTALLED"
  info "  (also update $UNIT_REPO for redeploys), then:"
  info "  sudo systemctl daemon-reload && sudo systemctl restart $SERVICE_NAME"
fi

step "Done."
if [[ "${reply:-n}" =~ ^[Yy] ]]; then
  ok "panel '$PANEL_NAME' at $ADDR is flashed, verified, and registered."
else
  ok "panel '$PANEL_NAME' at $ADDR is flashed and verified (not yet registered -- see above)."
fi
