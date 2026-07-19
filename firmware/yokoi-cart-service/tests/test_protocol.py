from __future__ import annotations

import io
from pathlib import Path
import struct
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import yokoi_cart


class ProtocolTests(unittest.TestCase):
    def test_crc_reference_vector(self) -> None:
        self.assertEqual(yokoi_cart.crc16_ccitt(b"123456789"), 0x29B1)

    def test_frame_round_trip(self) -> None:
        encoded = yokoi_cart.encode_frame(0x10, 0x37, b"payload")
        frame = yokoi_cart.read_frame(io.BytesIO(b"noise" + encoded))
        self.assertEqual(frame.version, 1)
        self.assertEqual(frame.sequence, 0x37)
        self.assertEqual(frame.command, 0x10)
        self.assertEqual(frame.payload, b"payload")

    def test_frame_rejects_corrupt_crc(self) -> None:
        encoded = bytearray(yokoi_cart.encode_frame(0x01, 0, b""))
        encoded[-1] ^= 0x80
        with self.assertRaisesRegex(ValueError, "CRC mismatch"):
            yokoi_cart.read_frame(io.BytesIO(encoded))

    def test_device_matches_sequence_and_command(self) -> None:
        request_sequence = 0
        response_body = struct.pack("<BBBH", 1, request_sequence, 0x81, 2) + b"\x00x"
        response = b"YK" + response_body + struct.pack("<H", yokoi_cart.crc16_ccitt(response_body))

        class Duplex(io.BytesIO):
            def __init__(self, incoming: bytes):
                super().__init__(incoming)
                self.outgoing = bytearray()

            def write(self, data: bytes) -> int:
                self.outgoing.extend(data)
                return len(data)

            def flush(self) -> None:
                pass

        stream = Duplex(response)
        self.assertEqual(yokoi_cart.Device(stream).hello(), b"x")
        self.assertTrue(stream.outgoing.startswith(b"YK"))

    def test_cart_info_layout(self) -> None:
        footer = bytes.fromhex("ea000000f00000010001030004000000")
        data = bytes((0x0F, 0x83, 0x87, 0x01, 0x00))
        data += struct.pack("<II", 1024 * 1024, 32 * 1024) + footer
        response_payload = b"\x00" + data
        response_body = struct.pack("<BBBH", 1, 0, 0x82, len(response_payload)) + response_payload
        response = b"YK" + response_body + struct.pack("<H", yokoi_cart.crc16_ccitt(response_body))

        class Duplex(io.BytesIO):
            def write(self, data: bytes) -> int:
                return len(data)

            def flush(self) -> None:
                pass

        info = yokoi_cart.Device(Duplex(response)).cart_info()
        self.assertTrue(info.footer_valid)
        self.assertEqual(info.model, 0x83)
        self.assertEqual(info.rom_size, 1024 * 1024)
        self.assertEqual(info.save_size, 32 * 1024)
        self.assertEqual(info.footer, footer)

    def test_xmodem_boot_transfer(self) -> None:
        class Duplex(io.BytesIO):
            def __init__(self, incoming: bytes):
                super().__init__(incoming)
                self.outgoing = bytearray()

            def write(self, data: bytes) -> int:
                self.outgoing.extend(data)
                return len(data)

            def flush(self) -> None:
                pass

        stream = Duplex(bytes((yokoi_cart.XMODEM_NAK, yokoi_cart.XMODEM_ACK, yokoi_cart.XMODEM_ACK)))
        yokoi_cart.xmodem_send(stream, b"bF\xff\xffpayload")
        self.assertEqual(stream.outgoing[0], yokoi_cart.XMODEM_SOH)
        self.assertEqual(stream.outgoing[1:3], b"\x01\xfe")
        self.assertEqual(stream.outgoing[-1], yokoi_cart.XMODEM_EOT)

    def test_prepare_write_returns_token(self) -> None:
        response_payload = b"\x00\x34\x12"
        response_body = struct.pack("<BBBH", 1, 0, 0xB0, len(response_payload)) + response_payload
        response = b"YK" + response_body + struct.pack("<H", yokoi_cart.crc16_ccitt(response_body))

        class Duplex(io.BytesIO):
            def write(self, data: bytes) -> int:
                return len(data)

            def flush(self) -> None:
                pass

        token = yokoi_cart.Device(Duplex(response)).prepare_write(1, 32768, 0x89ABCDEF)
        self.assertEqual(token, 0x1234)


if __name__ == "__main__":
    unittest.main()
# SPDX-License-Identifier: GPL-3.0-or-later
