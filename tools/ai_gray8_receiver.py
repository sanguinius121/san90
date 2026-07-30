#!/usr/bin/env python3
"""Standalone validator/preview receiver for SAN-90 GRAY8 waterfall images."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.ai_stream.protocol import validate_multipart


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connect", default="tcp://127.0.0.1:5557")
    parser.add_argument("--save-dir", type=Path)
    parser.add_argument("--save-every", type=int, default=10)
    parser.add_argument("--max-files", type=int, default=20)
    parser.add_argument("--stop-after", type=int, help="Exit after receiving N valid images")
    parser.add_argument("--display", action="store_true")
    args = parser.parse_args()
    if args.save_every < 1 or args.max_files < 1:
        parser.error("--save-every and --max-files must be positive")
    if args.stop_after is not None and args.stop_after < 1:
        parser.error("--stop-after must be positive")
    return args


def save_preview(directory: Path, image: np.ndarray, metadata: dict[str, object], max_files: int) -> None:
    from PIL import Image

    directory.mkdir(parents=True, exist_ok=True)
    stem = f"received_san90_gray8_{int(metadata['sequence']):012d}_{int(metadata['timestamp_ns'])}"
    Image.fromarray(image, mode="L").save(directory / f"{stem}.png", format="PNG")
    (directory / f"{stem}.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    files = sorted(directory.glob("received_san90_gray8_*.png"), key=lambda path: path.stat().st_mtime_ns)
    for path in files[:-max_files]:
        path.unlink(missing_ok=True)
        path.with_suffix(".json").unlink(missing_ok=True)


def main() -> int:
    args = parse_args()
    try:
        import zmq
    except ImportError:
        print("pyzmq is required: python3 -m pip install -r backend/requirements.txt", file=sys.stderr)
        return 2
    cv2 = None
    if args.display:
        try:
            import cv2 as cv2_module
            cv2 = cv2_module
        except ImportError:
            print("--display requires optional OpenCV; receiving will continue without a window", file=sys.stderr)
    context = zmq.Context.instance()
    socket = context.socket(zmq.PULL)
    socket.setsockopt(zmq.RCVHWM, 2)
    socket.connect(args.connect)
    received = 0
    reported_at = time.monotonic()
    reported_count = 0
    print(f"Receiving SAN-90 GRAY8 images from {args.connect}")
    try:
        while True:
            parts = socket.recv_multipart()
            if len(parts) != 2:
                print(f"Rejected malformed message with {len(parts)} parts", file=sys.stderr)
                continue
            try:
                metadata, image = validate_multipart(parts[0], parts[1])
            except ValueError as error:
                print(f"Rejected malformed message: {error}", file=sys.stderr)
                continue
            received += 1
            if args.save_dir is not None and received % args.save_every == 0:
                save_preview(args.save_dir, image, metadata, args.max_files)
            if args.stop_after is not None and received >= args.stop_after:
                print(f"Received {received} valid images; stopping.")
                break
            if cv2 is not None:
                cv2.imshow("SAN-90 GRAY8 waterfall", image)
                if cv2.waitKey(1) & 0xFF in (27, ord("q")):
                    break
            now = time.monotonic()
            if now - reported_at >= 1.0:
                count = received - reported_count
                duration_ms = (
                    int(metadata["capture_end_timestamp_ns"]) - int(metadata["capture_start_timestamp_ns"])
                ) / 1e6
                print(
                    f"sequence={metadata['sequence']} receive_fps={count/(now-reported_at):.2f} "
                    f"payload={len(parts[1])} profile={metadata['power_profile']} "
                    f"limits=[{metadata['power_min_dbm']},{metadata['power_max_dbm']}]dBm "
                    f"center={float(metadata['center_frequency_hz'])/1e9:.9f}GHz "
                    f"start/stop={float(metadata['start_frequency_hz'])/1e9:.9f}/"
                    f"{float(metadata['stop_frequency_hz'])/1e9:.9f}GHz duration={duration_ms:.3f}ms "
                    f"clip_low/high={float(metadata['clipped_low_ratio']):.6f}/"
                    f"{float(metadata['clipped_high_ratio']):.6f} "
                    f"min/max={float(metadata['image_min_dbm']):.2f}/{float(metadata['image_max_dbm']):.2f}dBm"
                )
                reported_at = now
                reported_count = received
    except KeyboardInterrupt:
        pass
    finally:
        socket.close(linger=0)
        if cv2 is not None:
            cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
