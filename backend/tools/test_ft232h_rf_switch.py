#!/usr/bin/env python3
"""Standalone FT232H RF-switch verification utility.

Every command restores RF8 before releasing the controller.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.hardware.rf_switch.ft232h_switch import FTDI_URL, Ft232hRfSwitch, gpio_value_to_address
from backend.hardware.rf_switch.models import PATH_LABELS, PATH_TO_ADDRESS, RfPath, parse_rf_path


def print_state(switch: Ft232hRfSwitch, requested: RfPath) -> bool:
    reported = switch.get_path()
    raw = switch.raw_gpio_value
    address = gpio_value_to_address(raw or 0)
    passed = reported is requested and address == PATH_TO_ADDRESS[requested]
    print(f"Requested: {requested.value} — {PATH_LABELS[requested]}")
    print(f"Reported RF channel: RF{PATH_TO_ADDRESS[reported] + 1}")
    print(f"AD6:AD5:AD4: {address:03b}")
    print(f"Raw GPIO: 0x{(raw or 0):02X}")
    print(f"Verification: {'PASS' if passed else 'FAIL'}")
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "set", "cycle"))
    parser.add_argument("path", nargs="?", help="rf1 through rf8 for the set command")
    parser.add_argument("--url", default=FTDI_URL)
    parser.add_argument("--settle-ms", type=float, default=5.0)
    args = parser.parse_args()
    if args.command == "set" and args.path is None:
        parser.error("set requires an RF path")

    switch = Ft232hRfSwitch(args.url, settle_s=args.settle_ms / 1000.0)
    success = True
    try:
        switch.open()
        if args.command == "status":
            success = print_state(switch, switch.get_path())
        elif args.command == "set":
            path = parse_rf_path(args.path)
            switch.set_path(path)
            success = print_state(switch, path)
        else:
            for path in RfPath:
                switch.set_path(path)
                success = print_state(switch, path) and success
                print()
            if PATH_TO_ADDRESS[RfPath.RF2_AUXILIARY] != 0b001:
                success = False
            switch.set_path(RfPath.RF8_WIDEBAND_ANTENNA)
            success = print_state(switch, RfPath.RF8_WIDEBAND_ANTENNA) and success
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        success = False
    finally:
        switch.close()
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
