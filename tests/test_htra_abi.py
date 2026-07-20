from __future__ import annotations

import ctypes as ct
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from backend.analyzer.htra import (
    BootInfo,
    BootProfile,
    MeasAuxInfo,
    NativeDeviceInfo,
    NativeFirmwareVersion,
    RtaFrameInfo,
    RtaPlotInfo,
    RtaProfile,
    TriggerInfo,
)


ROOT = Path(__file__).resolve().parents[1]
HEADER_DIR = ROOT / "harogic" / "Linux_API" / "htraapi" / "inc"


class HtraAbiTests(unittest.TestCase):
    def test_ctypes_layouts_match_canonical_header(self) -> None:
        compiler = shutil.which("c++") or shutil.which("g++")
        if compiler is None:
            self.skipTest("C++ compiler unavailable")
        source = r'''
#include <stddef.h>
#include <stdbool.h>
#include <stdio.h>
#include "htra_api.h"
#define SIZE(T) printf(#T "=%zu\n", sizeof(T))
int main(void) {
  SIZE(BootProfile_TypeDef);
  SIZE(DeviceInfo_TypeDef);
  SIZE(DeviceFirmwareVersion_TypeDef);
  SIZE(BootInfo_TypeDef);
  SIZE(MeasAuxInfo_TypeDef);
  SIZE(TriggerInfo_TypeDef);
  SIZE(RTA_Profile_TypeDef);
  SIZE(RTA_FrameInfo_TypeDef);
  SIZE(RTA_PlotInfo_TypeDef);
  printf("RTA_Profile.EnableIFAGC=%zu\n", offsetof(RTA_Profile_TypeDef, EnableIFAGC));
  printf("RTA_Profile.DCCancelerMode=%zu\n", offsetof(RTA_Profile_TypeDef, DCCancelerMode));
  printf("MeasAux.nsSinceEpoch=%zu\n", offsetof(MeasAuxInfo_TypeDef, nsSinceEpoch));
  return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="san90-abi-") as temporary:
            temporary_path = Path(temporary)
            c_file = temporary_path / "probe.c"
            executable = temporary_path / "probe"
            c_file.write_text(source, encoding="utf-8")
            subprocess.run(
                [compiler, "-std=c++11", "-x", "c++", "-I", str(HEADER_DIR), str(c_file), "-o", str(executable)],
                check=True,
                capture_output=True,
                text=True,
            )
            result = subprocess.run([str(executable)], check=True, capture_output=True, text=True)
        actual = dict(line.split("=", 1) for line in result.stdout.splitlines())
        expected = {
            "BootProfile_TypeDef": ct.sizeof(BootProfile),
            "DeviceInfo_TypeDef": ct.sizeof(NativeDeviceInfo),
            "DeviceFirmwareVersion_TypeDef": ct.sizeof(NativeFirmwareVersion),
            "BootInfo_TypeDef": ct.sizeof(BootInfo),
            "MeasAuxInfo_TypeDef": ct.sizeof(MeasAuxInfo),
            "TriggerInfo_TypeDef": ct.sizeof(TriggerInfo),
            "RTA_Profile_TypeDef": ct.sizeof(RtaProfile),
            "RTA_FrameInfo_TypeDef": ct.sizeof(RtaFrameInfo),
            "RTA_PlotInfo_TypeDef": ct.sizeof(RtaPlotInfo),
            "RTA_Profile.EnableIFAGC": RtaProfile.EnableIFAGC.offset,
            "RTA_Profile.DCCancelerMode": RtaProfile.DCCancelerMode.offset,
            "MeasAux.nsSinceEpoch": MeasAuxInfo.nsSinceEpoch.offset,
        }
        self.assertEqual({key: int(value) for key, value in actual.items()}, expected)


if __name__ == "__main__":
    unittest.main()
