from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tools.ai_gray8_receiver import (
    build_labelme_document,
    detect_candidate_boxes,
    parse_args,
    save_preview,
)


def metadata(sequence: int = 1) -> dict[str, object]:
    return {
        "sequence": sequence,
        "timestamp_ns": 123456789 + sequence,
        "db_per_gray_level": 100.0 / 255.0,
        "power_min_dbm": -120.0,
        "power_max_dbm": -20.0,
    }


class AiGray8ReceiverArgumentsTests(unittest.TestCase):
    def test_auto_labelme_is_opt_in_and_defaults_are_stable(self) -> None:
        args = parse_args([])
        self.assertFalse(args.auto_labelme)
        self.assertEqual(args.threshold_db, 6.0)
        self.assertEqual(args.auto_label, "AUTO_CANDIDATE")

    def test_auto_labelme_accepts_flag_and_explicit_boolean(self) -> None:
        self.assertTrue(parse_args(["--auto-labelme"]).auto_labelme)
        self.assertTrue(parse_args(["--auto-labelme=true"]).auto_labelme)
        self.assertFalse(parse_args(["--auto-labelme=false"]).auto_labelme)


class CandidateDetectionTests(unittest.TestCase):
    def test_detects_wide_region_and_each_narrow_burst_separately(self) -> None:
        image = np.full((640, 640), 80, dtype=np.uint8)
        image[100:120, 180:290] = 130
        burst_rows = list(range(20, 600, 40))
        for y in burst_rows:
            image[y : y + 2, 380:390] = 130

        boxes = detect_candidate_boxes(image, metadata(), threshold_db=6.0)

        self.assertEqual(len(boxes), 1 + len(burst_rows))
        self.assertTrue(any(x0 <= 180 and y0 <= 100 and x1 >= 290 and y1 >= 120 for x0, y0, x1, y1 in boxes))
        narrow_boxes = [box for box in boxes if box[0] <= 380 and box[2] >= 390]
        self.assertEqual(len(narrow_boxes), len(burst_rows))
        self.assertTrue(all(y1 - y0 <= 10 for _, y0, _, y1 in narrow_boxes))

    def test_threshold_is_relative_to_each_frequency_column(self) -> None:
        image = np.tile(np.linspace(50, 110, 640, dtype=np.uint8), (640, 1))
        image[200:220, 300:360] = np.minimum(image[200:220, 300:360] + 30, 255)

        boxes = detect_candidate_boxes(image, metadata(), threshold_db=6.0)

        self.assertEqual(len(boxes), 1)
        self.assertTrue(boxes[0][0] <= 300 <= boxes[0][2])

    def test_fragments_in_one_burst_merge_without_joining_time_separated_bursts(self) -> None:
        image = np.full((640, 640), 80, dtype=np.uint8)
        image[100:103, 200:210] = 130
        image[100:103, 212:222] = 130
        image[140:143, 200:222] = 130

        boxes = detect_candidate_boxes(image, metadata(), threshold_db=6.0)

        self.assertEqual(len(boxes), 2)
        self.assertTrue(any(x0 <= 200 and x1 >= 222 and y0 <= 100 <= y1 for x0, y0, x1, y1 in boxes))

    def test_builds_labelme_rectangles_with_placeholder_label(self) -> None:
        image = np.zeros((640, 640), dtype=np.uint8)
        document = build_labelme_document(
            "capture.png",
            image,
            [(1, 2, 30, 40)],
            label="AUTO_CANDIDATE",
            threshold_db=6.0,
        )
        self.assertEqual(document["imagePath"], "capture.png")
        self.assertEqual(document["imageWidth"], 640)
        self.assertEqual(document["shapes"][0]["shape_type"], "rectangle")
        self.assertEqual(document["shapes"][0]["label"], "AUTO_CANDIDATE")


class PreviewSavingTests(unittest.TestCase):
    def test_default_mode_preserves_original_metadata_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            save_preview(directory, np.full((640, 640), 80, dtype=np.uint8), metadata(), 20)
            json_path = next(directory.glob("*.json"))
            saved = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["sequence"], 1)
            self.assertNotIn("shapes", saved)
            self.assertFalse(list(directory.glob("*.meta.json")))

    def test_auto_mode_writes_labelme_and_preserves_metadata_separately(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            image = np.full((640, 640), 80, dtype=np.uint8)
            image[100:120, 180:290] = 130
            save_preview(
                directory,
                image,
                metadata(),
                20,
                auto_labelme=True,
                threshold_db=6.0,
                auto_label="AUTO_CANDIDATE",
            )
            label_path = next(path for path in directory.glob("*.json") if not path.name.endswith(".meta.json"))
            labelme = json.loads(label_path.read_text(encoding="utf-8"))
            saved_metadata = json.loads(label_path.with_suffix(".meta.json").read_text(encoding="utf-8"))
            self.assertEqual(labelme["imagePath"], label_path.with_suffix(".png").name)
            self.assertEqual(labelme["shapes"][0]["label"], "AUTO_CANDIDATE")
            self.assertEqual(saved_metadata["sequence"], 1)

    def test_rotation_removes_png_label_and_metadata_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            image = np.full((640, 640), 80, dtype=np.uint8)
            save_preview(directory, image, metadata(1), 1, auto_labelme=True)
            save_preview(directory, image, metadata(2), 1, auto_labelme=True)
            self.assertEqual(len(list(directory.glob("*.png"))), 1)
            label_paths = [path for path in directory.glob("*.json") if not path.name.endswith(".meta.json")]
            self.assertEqual(len(label_paths), 1)
            self.assertEqual(len(list(directory.glob("*.meta.json"))), 1)


if __name__ == "__main__":
    unittest.main()
