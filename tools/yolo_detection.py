#!/usr/bin/env python3
"""Realtime YOLO detector for SAN-90 GRAY8 waterfall images.

Connects to the same ZeroMQ PULL socket used by ai_gray8_receiver.py
(default tcp://127.0.0.1:5557), decodes each 640x640 GRAY8 frame, runs it
through a YOLO model and prints the detected labels to the terminal.

Publishes two channels:
- --publish (default tcp://127.0.0.1:5558): lightweight detections JSON,
  consumed by backend/ai_detection.py.
- --review-publish (default tcp://127.0.0.1:5555): [json metadata, raw JPEG,
  annotated JPEG] multipart, consumed by backend/ai_detection_review.py for
  the AI review panel and the save-to-disk action.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
import zmq
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.ai_stream.protocol import validate_multipart

BOX_COLORS = [
    (0, 255, 0),
    (255, 0, 0),
    (0, 0, 255),
    (0, 255, 255),
    (255, 0, 255),
    (255, 255, 0),
]
#PUB
def make_result_publisher(context, bind_addr: str):
    """PUB socket để bắn kết quả detection ra cho web backend hứng."""
    pub = context.socket(zmq.PUB)
    pub.setsockopt(zmq.SNDHWM, 10)   
    pub.bind(bind_addr)
    return pub
#public
def publish_result(
    pub,
    metadata: dict,
    detections: list[dict],
    class_names: dict,
    label_freq_ranges: dict[int, tuple[float, float]],
) -> None:
    payload = {
        "sequence": int(metadata["sequence"]),
        "timestamp_ns": int(metadata["timestamp_ns"]),
        "generated_at": time.time(),
        "detections": [
            {
                "class_id": det["class"],
                "label": str(class_names.get(det["class"], det["class"])),
                "confidence": det["confidence"],
                "bbox": det["bbox"],
                "frequency_start_hz": det["frequency_start"],
                "frequency_stop_hz": det["frequency_stop"],
            }
            for det in detections
        ],
        "label_freq_ranges_hz": {
            str(class_names.get(cls, cls)): {"start_hz": lo, "stop_hz": hi}
            for cls, (lo, hi) in label_freq_ranges.items()
        },
    }
    try:
        pub.send_string(json.dumps(payload), flags=zmq.NOBLOCK)
    except zmq.Again:
        pass
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connect", default="tcp://127.0.0.1:5557")
    parser.add_argument(
        "--model",
        default=str(Path(__file__).resolve().parents[1] / "ai_detect" / "weights" / "best_openvino_model"),
        help="Path to YOLO weights (.pt or OpenVINO model directory)",
    )
    parser.add_argument("--conf", type=float, default=0.5, help="Confidence threshold")
    parser.add_argument("--device", default=None, help="Inference device, e.g. 'cpu' or '0' (GPU)")
    parser.add_argument("--save-dir", type=Path, help="Directory to save annotated detection images")
    parser.add_argument("--save-every", type=int, default=10, help="Save every Nth received frame")
    parser.add_argument("--max-files", type=int, default=50, help="Keep at most this many saved images")
    parser.add_argument(
        "--publish",
        default="tcp://127.0.0.1:5558",
        help="PUB endpoint for lightweight detections JSON (consumed by backend/ai_detection.py)",
    )
    parser.add_argument(
        "--publish-fps",
        type=float,
        default=20.0,
    )
    parser.add_argument(
        "--review-publish",
        default="tcp://127.0.0.1:5555",
        help="PUB endpoint for the annotated-review channel (metadata + raw/annotated JPEGs)",
    )
    parser.add_argument(
        "--review-publish-fps",
        type=float,
        default=5.0,
        help="Max publish rate for the heavier review channel (images)",
    )
    parser.add_argument(
        "--results-path",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "ai_detect" / "latest.json",
        help="Where to write the latest detection results as JSON (consumed by the web backend)",
    )
    args = parser.parse_args()
    if not (0.0 <= args.conf <= 1.0):
        parser.error("--conf must be between 0 and 1")
    if args.save_every < 1 or args.max_files < 1:
        parser.error("--save-every and --max-files must be positive")
    return args


def draw_detections(cv2, frame, detections: list[dict], class_names: dict):
    """Return a copy of frame with detection boxes/labels drawn on it."""
    annotated = frame.copy()

    for det in detections:
        class_id = det["class"]
        confidence = det["confidence"]
        x1, y1, x2, y2 = (int(v) for v in det["bbox"])
        color = BOX_COLORS[class_id % len(BOX_COLORS)]
        label = f"{class_names.get(class_id, class_id)} {confidence:.2f}"

        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        text_size, baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        text_w, text_h = text_size
        y_text = max(y1, text_h + baseline + 4)
        cv2.rectangle(annotated, (x1, y_text - text_h - baseline - 4), (x1 + text_w + 6, y_text), color, -1)
        cv2.putText(
            annotated, label, (x1 + 3, y_text - baseline - 2),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2,
        )

    return annotated


def save_detection_image(
    cv2,
    directory: Path,
    annotated,
    metadata: dict,
    max_files: int,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)

    stem = f"detect_san90_gray8_{int(metadata['sequence']):012d}_{int(metadata['timestamp_ns'])}"
    cv2.imwrite(str(directory / f"{stem}.png"), annotated)

    files = sorted(directory.glob("detect_san90_gray8_*.png"), key=lambda path: path.stat().st_mtime_ns)
    for path in files[:-max_files]:
        path.unlink(missing_ok=True)


def publish_review(
    cv2,
    pub,
    metadata: dict,
    raw_frame,
    annotated_frame,
    detections: list[dict],
    class_names: dict,
    label_freq_ranges: dict[int, tuple[float, float]],
) -> None:
    """Send [json metadata, raw JPEG, annotated JPEG] for the AI review panel."""
    ok_raw, raw_encoded = cv2.imencode(".jpg", raw_frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    ok_annotated, annotated_encoded = cv2.imencode(".jpg", annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok_raw or not ok_annotated:
        return

    payload = {
        "sequence": int(metadata["sequence"]),
        "timestamp_ns": int(metadata["timestamp_ns"]),
        "generated_at": time.time(),
        "width": int(metadata["width"]),
        "height": int(metadata["height"]),
        "center_frequency_hz": metadata["center_frequency_hz"],
        "start_frequency_hz": metadata["start_frequency_hz"],
        "stop_frequency_hz": metadata["stop_frequency_hz"],
        "content_type": "image/jpeg",
        "detections": [
            {
                "class_id": det["class"],
                "label": str(class_names.get(det["class"], det["class"])),
                "confidence": det["confidence"],
                "bbox": det["bbox"],
            }
            for det in detections
        ],
        "label_freq_ranges_hz": {
            str(class_names.get(cls, cls)): {"start_hz": lo, "stop_hz": hi}
            for cls, (lo, hi) in label_freq_ranges.items()
        },
    }
    # Optional v1 metadata extension. Older producers remain compatible while
    # current SAN-90 backends can correlate the annotated preview with the
    # exact absolute-dBm mapping used to create its GRAY8 input.
    for field in (
        "power_min_dbm",
        "power_max_dbm",
        "power_range_db",
        "db_per_gray_level",
        "power_range_generation",
        "power_profile",
    ):
        if field in metadata:
            payload[field] = metadata[field]
    try:
        pub.send_multipart(
            [
                json.dumps(payload).encode("utf-8"),
                raw_encoded.tobytes(),
                annotated_encoded.tobytes(),
            ],
            flags=zmq.NOBLOCK,
        )
    except zmq.Again:
        pass


def write_latest_results(
    path: Path,
    metadata: dict,
    detections: list[dict],
    class_names: dict,
) -> None:
    payload = {
        "sequence": int(metadata["sequence"]),
        "timestamp_ns": int(metadata["timestamp_ns"]),
        "generated_at": time.time(),
        "detections": [
            {
                "class_id": det["class"],
                "label": str(class_names.get(det["class"], det["class"])),
                "confidence": det["confidence"],
                "bbox": det["bbox"],
            }
            for det in detections
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    tmp_path.replace(path)
NOISE_CLS = 1


@dataclass
class SimpleCapture:
    start_frequency_hz: float
    stop_frequency_hz: float

def freq_range_per_label(boxes, capture, img_w=640, exclude={NOISE_CLS}):
    """boxes: list of (cls, xc, yc, w, h). Trả về {cls: (f_start, f_stop)}."""
    f0, f1 = capture.start_frequency_hz, capture.stop_frequency_hz
    hz_per_px = (f1 - f0) / (img_w - 1)

    def freq(x_norm):
        return f0 + (x_norm * img_w - 0.5) * hz_per_px

    result = {}
    for cls, xc, yc, w, h in boxes:
        if cls in exclude:
            continue
        lo, hi = freq(xc - w / 2), freq(xc + w / 2)
        if cls in result:
            prev_lo, prev_hi = result[cls]
            result[cls] = (min(prev_lo, lo), max(prev_hi, hi))
        else:
            result[cls] = (lo, hi)
    return result


def main() -> int:
    args = parse_args()

    try:
        import cv2
    except ImportError:
        print("opencv-python is required: python3 -m pip install opencv-python", file=sys.stderr)
        return 2

    try:
        from ultralytics import YOLO
    except ImportError:
        print("ultralytics is required: python3 -m pip install ultralytics", file=sys.stderr)
        return 2

    print(f"Loading YOLO model from {args.model}")
    model = YOLO(args.model, task="detect")
    class_names = model.names

    context = zmq.Context.instance()
    socket = context.socket(zmq.PULL)
    socket.setsockopt(zmq.RCVHWM, 2)
    socket.connect(args.connect)

    print(f"Receiving SAN-90 GRAY8 images from {args.connect}")
    print(f"Writing latest detection results to {args.results_path}")
    if args.save_dir is not None:
        print(f"Saving annotated detections to {args.save_dir} (every {args.save_every} frames)")
    result_pub = None
    if args.publish:
        result_pub = make_result_publisher(context, args.publish)
        print(f"Publishing detection results to {args.publish} (max {args.publish_fps:.0f} fps)")

    review_pub = None
    if args.review_publish:
        review_pub = make_result_publisher(context, args.review_publish)
        print(f"Publishing AI review (images) to {args.review_publish} (max {args.review_publish_fps:.0f} fps)")

    publish_interval = 1.0 / args.publish_fps if args.publish_fps > 0 else 0.0
    last_publish = 0.0
    review_publish_interval = 1.0 / args.review_publish_fps if args.review_publish_fps > 0 else 0.0
    last_review_publish = 0.0
    received = 0
    label_freq_ranges: dict[int, tuple[float, float]] = {}
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

            # YOLO expects a 3-channel image; the source frame is single-channel GRAY8.
            frame = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

            results = model.predict(source=frame, conf=args.conf, device=args.device, verbose=False)

            detections = []
            for result in results:
                if result.boxes is None:
                    continue
                for box in result.boxes:
                    detections.append({
                        "class": int(box.cls[0]),
                        "confidence": float(box.conf[0]),
                        "bbox": box.xyxy[0].tolist(),
                    })

            labels = [f"{class_names.get(d['class'], d['class'])}:{d['confidence']:.2f}" for d in detections]

            timestamp = time.strftime("%H:%M:%S")
            print(f"[{timestamp}] sequence={metadata['sequence']} detections=[{', '.join(labels)}]")

            width = int(metadata["width"])
            height = int(metadata["height"])
            boxes = [
                (
                    det["class"],
                    (det["bbox"][0] + det["bbox"][2]) / 2 / width,
                    (det["bbox"][1] + det["bbox"][3]) / 2 / height,
                    (det["bbox"][2] - det["bbox"][0]) / width,
                    (det["bbox"][3] - det["bbox"][1]) / height,
                )
                for det in detections
            ]
            capture = SimpleCapture(metadata["start_frequency_hz"], metadata["stop_frequency_hz"])
            hz_per_px = (capture.stop_frequency_hz - capture.start_frequency_hz) / (width - 1)
            for det in detections:
                x1, _, x2, _ = det["bbox"]
                det["frequency_start"] = capture.start_frequency_hz + (x1 - 0.5) * hz_per_px
                det["frequency_stop"] = capture.start_frequency_hz + (x2 - 0.5) * hz_per_px
            for cls, (lo, hi) in freq_range_per_label(boxes, capture, img_w=width).items():
                if cls in label_freq_ranges:
                    prev_lo, prev_hi = label_freq_ranges[cls]
                    label_freq_ranges[cls] = (min(prev_lo, lo), max(prev_hi, hi))
                else:
                    label_freq_ranges[cls] = (lo, hi)

            write_latest_results(args.results_path, metadata, detections, class_names)
            if result_pub is not None:
                now = time.monotonic()
                if now - last_publish >= publish_interval:
                    publish_result(result_pub, metadata, detections, class_names, label_freq_ranges)
                    last_publish = now

            should_save = args.save_dir is not None and received % args.save_every == 0
            now = time.monotonic()
            should_review_publish = review_pub is not None and now - last_review_publish >= review_publish_interval
            if should_save or should_review_publish:
                annotated = draw_detections(cv2, frame, detections, class_names)
                if should_save:
                    save_detection_image(cv2, args.save_dir, annotated, metadata, args.max_files)
                if should_review_publish:
                    publish_review(
                        cv2, review_pub, metadata, frame, annotated,
                        detections, class_names, label_freq_ranges,
                    )
                    last_review_publish = now
    except KeyboardInterrupt:
        pass
    finally:
        socket.close(linger=0)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
