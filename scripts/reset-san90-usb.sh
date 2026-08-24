#!/usr/bin/env bash
set -euo pipefail

SAN90_USB_ID="${SAN90_USB_ID:-367f:0001}"

command -v lsusb >/dev/null 2>&1 || {
  printf 'Cannot reset SAN-90: lsusb is not installed.\n' >&2
  exit 1
}
command -v usbreset >/dev/null 2>&1 || {
  printf 'Cannot reset SAN-90: usbreset is not installed.\n' >&2
  exit 1
}

if pgrep -f '^([^[:space:]]*/)?python([0-9]+([.][0-9]+)*)? -m uvicorn backend\.main:app( |$)' >/dev/null 2>&1; then
  printf 'Refusing USB reset while the SAN-90 backend is running.\n' >&2
  exit 1
fi
if pgrep -x SAStudio4 >/dev/null 2>&1; then
  printf 'Refusing USB reset while SAStudio4 is running. Exit SAStudio4 first.\n' >&2
  exit 1
fi

device_count="$(lsusb -d "$SAN90_USB_ID" | wc -l)"
if [[ "$device_count" -ne 1 ]]; then
  printf 'Expected exactly one SAN-90 USB device (%s), found %s.\n' "$SAN90_USB_ID" "$device_count" >&2
  exit 1
fi

usbreset "$SAN90_USB_ID"

# usbreset returns after the kernel reset request. Give udev/libusb a short
# stable-discovery window before either application opens the analyzer.
stable=0
for _ in {1..30}; do
  if [[ "$(lsusb -d "$SAN90_USB_ID" | wc -l)" -eq 1 ]]; then
    stable=$((stable + 1))
    [[ "$stable" -ge 3 ]] && break
  else
    stable=0
  fi
  sleep 0.1
done
if [[ "$stable" -lt 3 ]]; then
  printf 'SAN-90 did not become stably visible after USB reset.\n' >&2
  exit 1
fi
printf 'SAN-90 USB handoff reset complete.\n'
