#!/usr/bin/env python3
"""Validate the Dialbug ROM, emulator evidence, and audio proof."""

from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import math
from pathlib import Path
import struct
import wave


ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "dialbug.wsc"
RELEASE = ROOT / "release"
WAV = RELEASE / "battery-glow-mednafen-proof.wav"
ALL_REPORT = RELEASE / "swansong-playtest-report.json"
OUTPUT = RELEASE / "verification-report.json"
INTERFACE_MASTER = ROOT / "assets/source-art/dialbug-sd-mobile-suit-imagegen-v5.png"
INTERFACE_RUNTIME = ROOT / "assets/runtime/dialbug-sd-mascot-v5.png"
INTERFACE_MASTER_SHA256 = (
    "228164e1875b03bd006ee8c6f64f48f205874facb3fce5f486e7c9cac6d5cf18"
)

SONGS = (
    ("BATTERY GLOW", 148),
    ("NEON RAINTRACE", 132),
    ("SOFT RESET SUNRISE", 106),
	("LAST SAVE POINT", 164),
	("SIGNAL BLOOM", 140),
)
STEPS_PER_LOOP = 8 * 16


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    return struct.unpack(">II", data[16:24])


def correlation(values: list[float], lag: int, start: int) -> float:
    left = values[start : len(values) - lag]
    right = values[start + lag :]
    if len(left) < 100:
        return 0.0
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum(
        (x - left_mean) * (y - right_mean) for x, y in zip(left, right)
    )
    left_power = sum((x - left_mean) ** 2 for x in left)
    right_power = sum((y - right_mean) ** 2 for y in right)
    denominator = math.sqrt(left_power * right_power)
    return numerator / denominator if denominator else 0.0


def inspect_audio(path: Path, bpm: int) -> dict[str, object]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_rate = wav.getframerate()
        sample_width = wav.getsampwidth()
        frame_count = wav.getnframes()
        raw = wav.readframes(frame_count)

    if channels != 2 or sample_rate != 48_000 or sample_width != 2:
        raise ValueError("audio proof must be 16-bit stereo PCM at 48 kHz")

    samples = array("h")
    samples.frombytes(raw)
    if not samples:
        raise ValueError("audio proof is empty")

    peak = max(abs(value) for value in samples) / 32768.0
    rms = math.sqrt(sum(value * value for value in samples) / len(samples)) / 32768.0
    dc_offset = (sum(samples) / len(samples)) / 32768.0
    duration = frame_count / sample_rate

    # The sequencer's 16th-note step is exactly 15/BPM seconds on the default
    # 40,704-clock frame. Compare 10 ms RMS-envelope windows so oscillator
    # phase does not hide a correctly repeating musical pattern.
    expected_period = STEPS_PER_LOOP * 15.0 / bpm
    window_frames = sample_rate // 100
    envelope: list[float] = []
    stride = window_frames * channels
    for offset in range(0, len(samples), stride):
        window = samples[offset : offset + stride]
        if not window:
            continue
        envelope.append(math.sqrt(sum(v * v for v in window) / len(window)))

    window_seconds = window_frames / sample_rate
    low_lag = int((expected_period - 0.55) / window_seconds)
    high_lag = int((expected_period + 0.55) / window_seconds)
    start = int(1.0 / window_seconds)
    candidates = (
        (correlation(envelope, lag, start), lag)
        for lag in range(low_lag, high_lag + 1)
    )
    loop_correlation, best_lag = max(candidates)
    measured_period = best_lag * window_seconds

    if duration < expected_period * 2.25:
        raise ValueError("audio proof does not contain at least two complete loops")
    if peak <= 0.001 or peak >= 0.99:
        raise ValueError(f"audio peak is implausible or clipping: {peak:.6f}")
    if rms <= 0.001:
        raise ValueError(f"audio proof is effectively silent: RMS {rms:.6f}")
    if abs(measured_period - expected_period) > 0.03:
        raise ValueError(
            f"measured loop {measured_period:.3f}s differs from expected "
            f"{expected_period:.3f}s"
        )
    if loop_correlation < 0.80:
        raise ValueError(f"loop-envelope correlation is too weak: {loop_correlation:.3f}")

    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": sha256(path),
        "byteCount": path.stat().st_size,
        "channels": channels,
        "sampleRate": sample_rate,
        "bitsPerSample": sample_width * 8,
        "sampleFrames": frame_count,
        "durationSeconds": round(duration, 6),
        "peakAbsoluteSample": round(peak, 8),
        "peakDBFS": round(20.0 * math.log10(peak), 6),
        "rms": round(rms, 8),
        "rmsDBFS": round(20.0 * math.log10(rms), 6),
        "dcOffset": round(dc_offset, 8),
        "expectedLoopSeconds": round(expected_period, 6),
        "measuredLoopSeconds": round(measured_period, 6),
        "loopPeriodErrorSeconds": round(measured_period - expected_period, 6),
        "loopEnvelopeCorrelation": round(loop_correlation, 6),
    }


def inspect_rom(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    if len(data) < 65_536 or len(data) > 16 * 1024 * 1024:
        raise ValueError("ROM size is outside Swan Song's supported range")
    if len(data) % 65_536:
        raise ValueError("ROM is not a whole number of 64 KiB banks")
    recorded_checksum = int.from_bytes(data[-2:], "little")
    real_checksum = sum(data[:-2]) & 0xFFFF
    if recorded_checksum != real_checksum:
        raise ValueError(
            f"ROM checksum mismatch: {recorded_checksum:04x} != {real_checksum:04x}"
        )
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": sha256(path),
        "byteCount": len(data),
        "bankCount": len(data) // 65_536,
        "recordedChecksum": recorded_checksum,
        "realChecksum": real_checksum,
        "footerHex": data[-16:].hex(),
    }


def inspect_interface_art() -> dict[str, object]:
    master_size = png_size(INTERFACE_MASTER)
    runtime_size = png_size(INTERFACE_RUNTIME)
    master_hash = sha256(INTERFACE_MASTER)
    if master_hash != INTERFACE_MASTER_SHA256:
        raise ValueError("ImageGen interface master changed without provenance review")
    if master_size != (1254, 1254):
        raise ValueError(f"unexpected interface master dimensions: {master_size}")
    if runtime_size != (72, 64):
        raise ValueError(f"runtime mascot is not 9x8 tiles: {runtime_size}")
    return {
        "generator": "OpenAI ImageGen built-in tool",
        "mode": "edit/reference-guided-generation",
        "master": {
            "path": str(INTERFACE_MASTER.relative_to(ROOT)),
            "sha256": master_hash,
            "width": master_size[0],
            "height": master_size[1],
        },
        "runtimeDerivative": {
            "path": str(INTERFACE_RUNTIME.relative_to(ROOT)),
            "sha256": sha256(INTERFACE_RUNTIME),
            "width": runtime_size[0],
            "height": runtime_size[1],
            "tileWidth": runtime_size[0] // 8,
            "tileHeight": runtime_size[1] // 8,
        },
    }


def inspect_swansong(rom_sha256: str) -> dict[str, object]:
    reports = []
    final_audio_hashes = set()
    for song_index, (title, bpm) in enumerate(SONGS, start=1):
        report_path = RELEASE / "tracks" / f"song-{song_index}-report.json"
        frame_path = RELEASE / "tracks" / f"song-{song_index}-frame.png"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("schema") != "swan-song-playtest-report-v1":
            raise ValueError(f"unexpected Swan Song report schema: {report_path}")
        if report.get("romSHA256") != rom_sha256:
            raise ValueError(f"Swan Song report is bound to a different ROM: {report_path}")
        audio = report.get("audio", {})
        if audio.get("nonzeroSamples", 0) <= 0:
            raise ValueError(f"Swan Song reported silent audio: {report_path}")
        if not 0.001 < audio.get("peakAbsoluteSample", 0) < 0.99:
            raise ValueError(f"Swan Song audio peak failed: {report_path}")
        width, height = png_size(frame_path)
        if (width, height) != (report.get("captureWidth"), report.get("captureHeight")):
            raise ValueError(f"capture dimensions disagree with report: {frame_path}")
        if sha256(frame_path) != report.get("capturePNG_SHA256"):
            raise ValueError(f"capture hash disagrees with report: {frame_path}")
        final_audio_hashes.add(audio["finalWindowWAVSHA256"])
        reports.append(
            {
                "songIndex": song_index,
                "title": title,
                "bpm": bpm,
                "report": str(report_path.relative_to(ROOT)),
                "capture": str(frame_path.relative_to(ROOT)),
                "captureSHA256": report["capturePNG_SHA256"],
                "audioSampleFrames": audio["sampleFrames"],
                "audioNonzeroSamples": audio["nonzeroSamples"],
                "audioPeakAbsoluteSample": audio["peakAbsoluteSample"],
                "finalWindowWAVSHA256": audio["finalWindowWAVSHA256"],
            }
        )
    if len(final_audio_hashes) != len(SONGS):
        raise ValueError("per-song final audio windows are not distinct")

    all_report = json.loads(ALL_REPORT.read_text(encoding="utf-8"))
    if all_report.get("romSHA256") != rom_sha256:
        raise ValueError("all-controls Swan Song report is bound to a different ROM")
    if all_report.get("scheduledInputTransitions") != 21:
        raise ValueError("all-controls input plan did not execute every transition")
    if all_report.get("audio", {}).get("nonzeroSamples", 0) <= 0:
        raise ValueError("all-controls Swan Song report has no audio")

    return {
        "engineBackend": all_report["engineBackend"],
        "engineBuildID": all_report["engineBuildID"],
        "hardwareModel": all_report["hardwareModel"],
        "openIPLIdentifier": all_report["openIPLIdentifier"],
        "allControlsReport": str(ALL_REPORT.relative_to(ROOT)),
        "scheduledInputTransitions": all_report["scheduledInputTransitions"],
        "scheduledInputFrames": all_report["scheduledInputFrames"],
        "songs": reports,
    }


def source_facts() -> list[dict[str, object]]:
    paths = [
        ROOT / "Makefile",
        ROOT / "wfconfig.toml",
        ROOT / "scripts" / "build_interface_art.py",
        ROOT / "scripts" / "normalize_wfprocess_c.py",
        *sorted((ROOT / "src").glob("*.[ch]")),
        *sorted(path for path in (ROOT / "assets").rglob("*") if path.is_file()),
    ]
    return [
        {
            "path": str(path.relative_to(ROOT)),
            "sha256": sha256(path),
            "byteCount": path.stat().st_size,
        }
        for path in paths
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    rom = inspect_rom(ROM)
    swansong = inspect_swansong(str(rom["sha256"]))
    mednafen = inspect_audio(WAV, SONGS[0][1])
    report = {
        "schema": "dialbug-release-verification-v1",
        "status": "pass",
        "release": "0.1.0-development-preview",
        "rom": rom,
        "soundtrack": {
            "songCount": len(SONGS),
            "stepsPerLoop": STEPS_PER_LOOP,
            "songs": [
                {"index": index, "title": title, "bpm": bpm}
                for index, (title, bpm) in enumerate(SONGS, start=1)
            ],
        },
        "interfaceArt": inspect_interface_art(),
        "swansong": swansong,
        "mednafenAudio": mednafen,
        "sourceFiles": source_facts(),
        "physicalHardware": {
            "status": "pending",
            "claim": "No physical WonderSwan-family or flash-cartridge test has been performed.",
        },
        "licensing": {
            "status": "pending-maintainer-declaration",
            "publicDistributionAuthorized": False,
        },
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
