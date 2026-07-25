import asyncio
import json
import os
import unittest
from unittest.mock import patch

import zmq
import zmq.asyncio

from backend.ai_detection import AiDetectionSubscriber, normalize_ai_detection_payload
from backend.api.protocol import HEADER_SIZE, MESSAGE_AI_DETECTIONS, unpack_header
from backend.api.service import AnalyzerService


def result_payload(sequence: int, label: str = "DJI_20MHz") -> dict[str, object]:
    return {
        "sequence": sequence,
        "timestamp_ns": 1_784_947_230_410_329_302 + sequence,
        "generated_at": 1_784_947_230.437,
        "detections": [{
            "class_id": 4,
            "label": label,
            "confidence": 0.86,
            "frequency_start": 5.731e9,
            "frequency_stop": 5.751e9,
        }],
        "label_freq_ranges_hz": {
            label: {"start_hz": 2.44e9, "stop_hz": 5.8e9},
        },
    }


class AiDetectionPayloadTests(unittest.TestCase):
    def test_valid_payload_is_current_frame_only(self) -> None:
        normalized = normalize_ai_detection_payload(result_payload(7))
        self.assertEqual(normalized["sequence"], 7)
        self.assertEqual(normalized["timestamp_ns"], 1_784_947_230_410_329_309)
        self.assertEqual(normalized["detections"], [{
            "class_id": 4,
            "label": "DJI_20MHz",
            "confidence": 0.86,
            "frequency_start": 5.731e9,
            "frequency_stop": 5.751e9,
        }])
        self.assertNotIn("label_freq_ranges_hz", normalized)

    def test_aliases_are_accepted_and_invalid_bounds_are_rejected(self) -> None:
        payload = result_payload(1)
        detection = payload["detections"][0]
        detection["frequency_start_hz"] = detection.pop("frequency_start")
        detection["frequency_stop_hz"] = detection.pop("frequency_stop")
        normalized = normalize_ai_detection_payload(payload)
        self.assertEqual(normalized["detections"][0]["frequency_start"], 5.731e9)
        detection["frequency_stop_hz"] = 5.0e9
        with self.assertRaisesRegex(ValueError, "bounds"):
            normalize_ai_detection_payload(payload)

    def test_service_forwards_latest_result_as_bounded_message_type(self) -> None:
        with patch.dict(os.environ, {"AI_DETECTION_SUB_ENABLED": "false"}):
            service = AnalyzerService("simulator")
        mailbox = service.register()
        normalized = normalize_ai_detection_payload(result_payload(9))
        service.publish_ai_detection_result(normalized)
        message = mailbox._messages[MESSAGE_AI_DETECTIONS]
        header = unpack_header(message)
        self.assertEqual(header["message_type"], MESSAGE_AI_DETECTIONS)
        forwarded = json.loads(message[HEADER_SIZE:])
        self.assertEqual(forwarded["sequence"], 9)
        self.assertEqual(forwarded["detections"][0]["label"], "DJI_20MHz")


class AiDetectionSubscriberTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.context = zmq.asyncio.Context()
        self.publisher = self.context.socket(zmq.PUB)
        self.publisher.setsockopt(zmq.LINGER, 0)
        port = self.publisher.bind_to_random_port("tcp://127.0.0.1")
        self.endpoint = f"tcp://127.0.0.1:{port}"

    async def asyncTearDown(self) -> None:
        self.publisher.close(linger=0)
        self.context.destroy(linger=0)

    async def _send_until(self, payload: dict[str, object], event: asyncio.Event) -> None:
        for _ in range(40):
            await self.publisher.send_json(payload)
            try:
                await asyncio.wait_for(event.wait(), 0.03)
                return
            except TimeoutError:
                pass
        self.fail("subscriber did not receive the sample payload")

    async def test_disconnect_and_reconnect_keeps_subscriber_alive(self) -> None:
        received: list[dict[str, object]] = []
        event = asyncio.Event()

        def publish(result: dict[str, object]) -> None:
            received.append(result)
            event.set()

        subscriber = AiDetectionSubscriber(self.endpoint, reconnect_delay_s=0.01)
        task = asyncio.create_task(subscriber.run(publish))
        try:
            await self._send_until(result_payload(1), event)
            self.assertEqual(received[-1]["sequence"], 1)
            event.clear()
            self.publisher.close(linger=0)
            await asyncio.sleep(0.05)
            self.publisher = self.context.socket(zmq.PUB)
            self.publisher.setsockopt(zmq.LINGER, 0)
            self.publisher.bind(self.endpoint)
            await self._send_until(result_payload(2, "ELRS"), event)
            self.assertEqual(received[-1]["sequence"], 2)
            self.assertFalse(task.done())
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_unavailable_ai_endpoint_does_not_stop_analyzer(self) -> None:
        unused = self.context.socket(zmq.PUB)
        unused.setsockopt(zmq.LINGER, 0)
        port = unused.bind_to_random_port("tcp://127.0.0.1")
        unused.close(linger=0)
        with patch.dict(os.environ, {
            "AI_DETECTION_SUB_ENABLED": "true",
            "AI_DETECTION_SUB_URL": f"tcp://127.0.0.1:{port}",
        }, clear=True):
            service = AnalyzerService("simulator")
            await service.start()
            try:
                await asyncio.sleep(0.08)
                self.assertTrue(service.running)
                self.assertTrue(service.status_payload()["acquisition_running"])
                self.assertGreater(service.status_payload()["sdk_frames_received"], 0)
            finally:
                await service.stop(disconnect=True)


if __name__ == "__main__":
    unittest.main()
