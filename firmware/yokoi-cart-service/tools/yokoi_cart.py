#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Host client for the Yokoi WonderSwan cartridge service."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import struct
import sys
import time
from typing import BinaryIO
import zlib


MAGIC = b"YK"
PROTOCOL_VERSION = 1
MAX_TRANSFER = 128

CMD_HELLO = 0x01
CMD_GET_CART_INFO = 0x02
CMD_READ_ROM = 0x10
CMD_READ_SRAM = 0x11
CMD_READ_EEPROM = 0x12
CMD_WRITE_SRAM = 0x20
CMD_WRITE_EEPROM = 0x21
CMD_PREPARE_WRITE = 0x30
CMD_BEGIN_WRITE = 0x31
CMD_CANCEL_WRITE = 0x32

XMODEM_SOH = 0x01
XMODEM_EOT = 0x04
XMODEM_ACK = 0x06
XMODEM_NAK = 0x15
XMODEM_CAN = 0x18

STATUS_NAMES = {
    0x00: "ok",
    0x01: "bad CRC",
    0x02: "bad length",
    0x03: "unsupported command or protocol",
    0x04: "range error",
    0x05: "write path is locked",
    0x06: "requested save-memory type is absent",
    0x07: "hold A+B on the console to confirm",
    0x08: "cartridge changed during the write session",
    0x09: "device readback verification failed",
    0x0A: "write session or chunk sequence is invalid",
    0x0B: "completed image CRC does not match",
}


class DeviceError(RuntimeError):
    def __init__(self, status: int):
        self.status = status
        super().__init__(STATUS_NAMES.get(status, f"device error 0x{status:02x}"))


def crc16_ccitt(data: bytes, initial: int = 0xFFFF) -> int:
    crc = initial
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


@dataclass(frozen=True)
class Frame:
    version: int
    sequence: int
    command: int
    payload: bytes


@dataclass(frozen=True)
class CartInfo:
    flags: int
    model: int
    system_control: int
    save_kind: int
    eeprom_address_bits: int
    rom_size: int
    save_size: int
    footer: bytes

    @property
    def footer_valid(self) -> bool:
        return bool(self.flags & 0x02 and self.flags & 0x04)


def encode_frame(command: int, sequence: int, payload: bytes = b"") -> bytes:
    if len(payload) > 0xFFFF:
        raise ValueError("payload is too large")
    body = struct.pack("<BBBH", PROTOCOL_VERSION, sequence, command, len(payload)) + payload
    return MAGIC + body + struct.pack("<H", crc16_ccitt(body))


def _read_exact(stream: BinaryIO, length: int) -> bytes:
    result = bytearray()
    while len(result) < length:
        chunk = stream.read(length - len(result))
        if not chunk:
            raise TimeoutError("timed out waiting for cartridge-service response")
        result.extend(chunk)
    return bytes(result)


def read_frame(stream: BinaryIO) -> Frame:
    matched = 0
    while matched < len(MAGIC):
        value = _read_exact(stream, 1)[0]
        if value == MAGIC[matched]:
            matched += 1
        else:
            matched = 1 if value == MAGIC[0] else 0

    header = _read_exact(stream, 5)
    version, sequence, command, length = struct.unpack("<BBBH", header)
    payload = _read_exact(stream, length)
    received_crc = struct.unpack("<H", _read_exact(stream, 2))[0]
    expected_crc = crc16_ccitt(header + payload)
    if received_crc != expected_crc:
        raise ValueError(f"response CRC mismatch: {received_crc:04x} != {expected_crc:04x}")
    return Frame(version, sequence, command, payload)


class Device:
    def __init__(self, stream: BinaryIO):
        self.stream = stream
        self.sequence = 0

    def request(self, command: int, payload: bytes = b"") -> bytes:
        sequence = self.sequence
        self.sequence = (self.sequence + 1) & 0xFF
        self.stream.write(encode_frame(command, sequence, payload))
        if hasattr(self.stream, "flush"):
            self.stream.flush()
        frame = read_frame(self.stream)
        if frame.version != PROTOCOL_VERSION:
            raise RuntimeError(f"device protocol version {frame.version} is unsupported")
        if frame.sequence != sequence or frame.command != (command | 0x80):
            raise RuntimeError("response does not match request")
        if not frame.payload:
            raise RuntimeError("response omitted its status byte")
        status = frame.payload[0]
        if status:
            raise DeviceError(status)
        return frame.payload[1:]

    def hello(self) -> bytes:
        return self.request(CMD_HELLO)

    def cart_info(self) -> CartInfo:
        data = self.request(CMD_GET_CART_INFO)
        if len(data) != 29:
            raise RuntimeError(f"unexpected cartridge-info length: {len(data)}")
        flags, model, system_control, save_kind, address_bits = data[:5]
        rom_size, save_size = struct.unpack_from("<II", data, 5)
        return CartInfo(
            flags=flags,
            model=model,
            system_control=system_control,
            save_kind=save_kind,
            eeprom_address_bits=address_bits,
            rom_size=rom_size,
            save_size=save_size,
            footer=data[13:29],
        )

    def read_rom(self, bank: int, offset: int, length: int) -> bytes:
        data = self.request(CMD_READ_ROM, struct.pack("<HHB", bank & 0xFFFF, offset, length))
        if len(data) != length:
            raise RuntimeError(f"short ROM read: {len(data)} != {length}")
        return data

    def read_sram(self, bank: int, offset: int, length: int) -> bytes:
        data = self.request(CMD_READ_SRAM, struct.pack("<HHB", bank & 0xFFFF, offset, length))
        if len(data) != length:
            raise RuntimeError(f"short SRAM read: {len(data)} != {length}")
        return data

    def read_eeprom(self, address: int, length: int) -> bytes:
        data = self.request(CMD_READ_EEPROM, struct.pack("<HB", address, length))
        if len(data) != length:
            raise RuntimeError(f"short EEPROM read: {len(data)} != {length}")
        return data

    def prepare_write(self, save_kind: int, size: int, crc32: int) -> int:
        data = self.request(CMD_PREPARE_WRITE, struct.pack("<BII", save_kind, size, crc32))
        if len(data) != 2:
            raise RuntimeError(f"unexpected prepare-write response length: {len(data)}")
        return struct.unpack("<H", data)[0]

    def begin_write(self, token: int) -> int:
        data = self.request(CMD_BEGIN_WRITE, struct.pack("<H", token))
        if len(data) != 4:
            raise RuntimeError(f"unexpected begin-write response length: {len(data)}")
        return struct.unpack("<I", data)[0]

    def write_save(self, save_kind: int, data: bytes) -> tuple[int, bool]:
        command = CMD_WRITE_SRAM if save_kind == 1 else CMD_WRITE_EEPROM
        result = self.request(command, data)
        if len(result) != 5:
            raise RuntimeError(f"unexpected write response length: {len(result)}")
        position, complete = struct.unpack("<IB", result)
        return position, bool(complete)

    def cancel_write(self) -> None:
        self.request(CMD_CANCEL_WRITE)


def xmodem_send(stream: BinaryIO, image: bytes, retries: int = 10) -> None:
    """Send one BootFriend-compatible, checksum-mode XMODEM image."""
    if len(image) < 4 or image[:2] != b"bF":
        raise ValueError("firmware is not a BootFriend .bfb image")
    if _read_exact(stream, 1)[0] != XMODEM_NAK:
        raise RuntimeError("Yokoi Boot did not request an XMODEM transfer")

    block_count = (len(image) + 127) // 128
    for block_index in range(block_count):
        block_id = (block_index + 1) & 0xFF
        chunk = image[block_index * 128 : (block_index + 1) * 128].ljust(128, b"\x1a")
        packet = bytes((XMODEM_SOH, block_id, block_id ^ 0xFF)) + chunk + bytes((sum(chunk) & 0xFF,))
        for attempt in range(retries):
            stream.write(packet)
            if hasattr(stream, "flush"):
                stream.flush()
            reply = _read_exact(stream, 1)[0]
            if reply == XMODEM_ACK:
                break
            if reply == XMODEM_CAN:
                raise RuntimeError("Yokoi Boot cancelled the transfer")
            if reply != XMODEM_NAK:
                raise RuntimeError(f"unexpected XMODEM response 0x{reply:02x}")
        else:
            raise RuntimeError(f"XMODEM block {block_index + 1} failed after {retries} attempts")

    for attempt in range(retries):
        stream.write(bytes((XMODEM_EOT,)))
        if hasattr(stream, "flush"):
            stream.flush()
        reply = _read_exact(stream, 1)[0]
        if reply == XMODEM_ACK:
            return
        if reply == XMODEM_CAN:
            raise RuntimeError("Yokoi Boot cancelled the transfer")
    raise RuntimeError("Yokoi Boot did not acknowledge the end of the transfer")


def boot_service(stream: BinaryIO, firmware: Path) -> None:
    image = firmware.read_bytes()
    print(f"Loading {firmware.name} through Yokoi Boot...", file=sys.stderr)
    xmodem_send(stream, image)
    time.sleep(0.1)


def read_save_linear(device: Device, info: CartInfo, position: int, count: int) -> bytes:
    if info.save_kind == 1:
        bank_count = (info.save_size + 0xFFFF) // 0x10000
        bank_index = position // 0x10000
        bank = (-bank_count + bank_index) & 0xFFFF
        return device.read_sram(bank, position & 0xFFFF, count)
    if info.save_kind == 2:
        return device.read_eeprom(position, count)
    raise RuntimeError("cartridge does not have writable save memory")


def restore_save(device: Device, info: CartInfo, source: Path, assume_yes: bool) -> None:
    image = source.read_bytes()
    if info.save_kind not in (1, 2) or not info.save_size:
        raise RuntimeError("cartridge footer does not declare SRAM or EEPROM save memory")
    if len(image) != info.save_size:
        raise RuntimeError(f"save image is {len(image)} bytes; cartridge requires {info.save_size}")
    if not assume_yes:
        answer = input(
            f"This will overwrite all {info.save_size} bytes of cartridge {save_name(info.save_kind)}. "
            "Type WRITE to continue: "
        )
        if answer != "WRITE":
            raise RuntimeError("write cancelled")

    expected_crc = zlib.crc32(image) & 0xFFFFFFFF
    token = device.prepare_write(info.save_kind, len(image), expected_crc)
    print("Hold A+B on the WonderSwan now...", file=sys.stderr)
    deadline = time.monotonic() + 20.0
    while True:
        try:
            device.begin_write(token)
            break
        except DeviceError as error:
            if error.status != 0x07 or time.monotonic() >= deadline:
                raise
            time.sleep(0.2)

    completed = False
    for position in range(0, len(image), MAX_TRANSFER):
        chunk = image[position : position + MAX_TRANSFER]
        next_position, completed = device.write_save(info.save_kind, chunk)
        if next_position != position + len(chunk):
            raise RuntimeError(f"device advanced to unexpected write position {next_position}")
        print(f"Writing save {next_position}/{len(image)}", file=sys.stderr)
    if not completed:
        raise RuntimeError("device did not mark the final write chunk complete")

    print("Performing host-side full readback...", file=sys.stderr)
    for position in range(0, len(image), MAX_TRANSFER):
        expected = image[position : position + MAX_TRANSFER]
        actual = read_save_linear(device, info, position, len(expected))
        if actual != expected:
            raise RuntimeError(f"full readback mismatch at save offset 0x{position:05x}")
    print(f"Save restored and verified (CRC32 {expected_crc:08x}).")


def model_name(value: int) -> str:
    return {0x00: "WonderSwan", 0x01: "Pocket Challenge V2", 0x82: "WonderSwan Color", 0x83: "SwanCrystal"}.get(
        value, f"unknown (0x{value:02x})"
    )


def save_name(value: int) -> str:
    return {0: "none", 1: "SRAM", 2: "EEPROM", 0xFF: "unknown"}.get(value, f"unknown ({value})")


def dump_rom(device: Device, info: CartInfo, output: Path) -> None:
    if not info.footer_valid or not info.rom_size or info.rom_size % 0x10000:
        raise RuntimeError("cartridge footer does not declare a supported ROM size")
    banks = info.rom_size // 0x10000
    checksum = 0
    final_bytes = b""
    with output.open("xb") as destination:
        for index in range(banks):
            bank = (-banks + index) & 0xFFFF
            for offset in range(0, 0x10000, MAX_TRANSFER):
                data = device.read_rom(bank, offset, MAX_TRANSFER)
                destination.write(data)
                checksum = (checksum + sum(data)) & 0xFFFF
                final_bytes = (final_bytes + data)[-2:]
            print(f"ROM bank {index + 1}/{banks}", file=sys.stderr)
    stored_checksum = int.from_bytes(final_bytes, "little")
    computed_checksum = (checksum - sum(final_bytes)) & 0xFFFF
    if stored_checksum != computed_checksum:
        raise RuntimeError(
            f"dumped ROM checksum mismatch: stored 0x{stored_checksum:04x}, "
            f"computed 0x{computed_checksum:04x}"
        )


def dump_save(device: Device, info: CartInfo, output: Path) -> None:
    if not info.save_size or info.save_kind not in (1, 2):
        raise RuntimeError("cartridge footer does not declare supported save memory")
    with output.open("xb") as destination:
        if info.save_kind == 1:
            banks = (info.save_size + 0xFFFF) // 0x10000
            remaining = info.save_size
            for index in range(banks):
                bank = (-banks + index) & 0xFFFF
                bank_length = min(remaining, 0x10000)
                for offset in range(0, bank_length, MAX_TRANSFER):
                    count = min(MAX_TRANSFER, bank_length - offset)
                    destination.write(device.read_sram(bank, offset, count))
                remaining -= bank_length
                print(f"SRAM bank {index + 1}/{banks}", file=sys.stderr)
        else:
            for address in range(0, info.save_size, MAX_TRANSFER):
                count = min(MAX_TRANSFER, info.save_size - address)
                destination.write(device.read_eeprom(address, count))
                print(f"EEPROM {address + count}/{info.save_size}", file=sys.stderr)


def open_device(port: str, timeout: float) -> BinaryIO:
    try:
        import serial
    except ImportError as error:
        raise SystemExit("pyserial is required for hardware access: python3 -m pip install pyserial") from error
    return serial.Serial(port=port, baudrate=38400, bytesize=8, parity="N", stopbits=1, timeout=timeout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="ExtFriend/USB serial device")
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument(
        "--boot",
        action="store_true",
        help="load the cartridge-service .bfb through Yokoi Boot before running the command",
    )
    parser.add_argument(
        "--firmware",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "yokoi-cart-service.bfb",
        help="BootFriend .bfb image used with --boot",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("info")
    rom_parser = subparsers.add_parser("dump-rom")
    rom_parser.add_argument("output", type=Path)
    save_parser = subparsers.add_parser("dump-save")
    save_parser.add_argument("output", type=Path)
    restore_parser = subparsers.add_parser("restore-save")
    restore_parser.add_argument("input", type=Path)
    restore_parser.add_argument(
        "--yes-really-write",
        action="store_true",
        help="skip the typed host confirmation; physical A+B confirmation is still mandatory",
    )
    args = parser.parse_args()

    with open_device(args.port, args.timeout) as stream:
        if args.boot:
            boot_service(stream, args.firmware)
        device = Device(stream)
        hello = device.hello()
        if len(hello) < 14 or hello[9:14] != b"YOKOI":
            raise RuntimeError("connected device is not Yokoi Cart Service")
        info = device.cart_info()
        if args.action == "info":
            print(f"Console: {model_name(info.model)}")
            print(f"Cartridge self-test: {'passed' if info.flags & 1 else 'not reported'}")
            print(f"Footer: {info.footer.hex()}")
            print(f"ROM: {info.rom_size} bytes")
            print(f"Save: {save_name(info.save_kind)}, {info.save_size} bytes")
        elif args.action == "dump-rom":
            dump_rom(device, info, args.output)
        elif args.action == "dump-save":
            dump_save(device, info, args.output)
        elif args.action == "restore-save":
            restore_save(device, info, args.input, args.yes_really_write)


if __name__ == "__main__":
    main()
