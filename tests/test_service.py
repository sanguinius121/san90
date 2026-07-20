import asyncio
import os
import unittest
from unittest.mock import patch

from backend.api.service import AnalyzerService, ClientMailbox
from backend.api.protocol import MESSAGE_SPECTRUM_TEMPORAL, unpack_header


class ClientMailboxTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_client_keeps_only_latest_message_per_type(self) -> None:
        mailbox = ClientMailbox()
        mailbox.offer(1, b'old-spectrum')
        mailbox.offer(1, b'new-spectrum')
        mailbox.offer(3, b'waterfall')
        messages = await asyncio.wait_for(mailbox.take(), 0.1)
        self.assertEqual(set(messages), {b'new-spectrum', b'waterfall'})
        self.assertEqual(mailbox.replaced, 1)

    async def test_simulator_uses_profile_aware_batch_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            service = AnalyzerService('simulator')
            await service.start()
            try:
                safe = service.status_payload()
                self.assertEqual((safe['waterfall_rows_per_second'], safe['waterfall_batches_per_second'], safe['waterfall_rows_per_batch']), (60.0, 60.0, 1))
                await service.apply_control(rbw_mode='manual', rbw_hz=300_000.0)
                await asyncio.sleep(.15)
                fast = service.status_payload()
                self.assertEqual((fast['waterfall_rows_per_second'], fast['waterfall_batches_per_second'], fast['waterfall_rows_per_batch']), (240.0, 60.0, 4))
                self.assertGreater(fast['waterfall_producer']['completed_batches'], 0)
            finally:
                await service.stop(disconnect=True)

    async def test_simulator_service_publishes_combined_temporal_spectrum(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            service = AnalyzerService('simulator')
            mailbox = service.register()
            await service.start()
            try:
                temporal = None
                for _ in range(10):
                    messages = await asyncio.wait_for(mailbox.take(), .25)
                    temporal = next((message for message in messages if message[5] == MESSAGE_SPECTRUM_TEMPORAL), None)
                    if temporal is not None:
                        break
                self.assertIsNotNone(temporal)
                header = unpack_header(temporal)
                self.assertGreaterEqual(header['traces_integrated'], 1)
                self.assertEqual(header['payload_length'], header['point_count'] * 8)
            finally:
                service.unregister(mailbox)
                await service.stop(disconnect=True)

    async def test_inconsistent_waterfall_environment_is_rejected(self) -> None:
        with patch.dict(os.environ, {
            'SAN90_WATERFALL_ROWS_PER_SECOND':'240',
            'SAN90_WATERFALL_BATCHES_PER_SECOND':'60',
            'SAN90_WATERFALL_ROWS_PER_BATCH':'3',
        }, clear=True):
            with self.assertRaisesRegex(ValueError, 'must equal'):
                AnalyzerService('simulator')

    async def test_adaptive_spectrum_and_webgl_overrides_are_rejected(self) -> None:
        with patch.dict(os.environ, {'SAN90_SPECTRUM_FPS':'120'}, clear=True):
            with self.assertRaisesRegex(ValueError, 'must be 60'):
                AnalyzerService('simulator')
        with patch.dict(os.environ, {'SAN90_WEBGL_TARGET_FPS':'120'}, clear=True):
            with self.assertRaisesRegex(ValueError, 'must be 60'):
                AnalyzerService('simulator')


if __name__ == '__main__':
    unittest.main()
