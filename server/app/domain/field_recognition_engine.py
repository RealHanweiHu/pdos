"""Offline extraction child process. No database, credentials, prompts or business writes."""

from __future__ import annotations

import csv
import hashlib
import importlib
import importlib.metadata
import json
import math
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

MAX_TEXT = 16000
MAX_PARTS = 4000
MAX_AUDIO_SECONDS = 300


def fingerprint(root: Path) -> str:
    """Hash relative names and bytes; also usable before configuring an offline model."""
    if not root.is_dir():
        raise ValueError("model_unavailable")
    files = sorted(p for p in root.rglob("*") if p.is_file())
    if not files or len(files) > 128:
        raise ValueError("model_unavailable")
    total = 0
    entries = []
    for path in files:
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("model_unavailable")
        total += path.stat().st_size
        if total > 4 * 1024**3:
            raise ValueError("model_unavailable")
        with path.open("rb") as stream:
            value = hashlib.file_digest(stream, "sha256").hexdigest()
        entries.append([path.relative_to(root).as_posix(), value])
    return hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()


def recognize(source: Path, config: dict[str, Any]) -> dict[str, Any]:
    root = Path(config["model_dir"])
    model_hash = fingerprint(root)
    if model_hash != config["model_sha256"]:
        raise ValueError("model_changed")
    result = ocr(source, config) if config["kind"] == "ocr" else speech(source, config)
    # Detect replacement while an extraction was running; do not publish a mixed-version result.
    if fingerprint(root) != model_hash:
        raise ValueError("model_changed")
    return result | {"model_sha256": model_hash, "policy_version": "field-extraction-1"}


def ocr(source: Path, config: dict[str, Any]) -> dict[str, Any]:
    image_module: Any = importlib.import_module("PIL.Image")
    image_ops = importlib.import_module("PIL.ImageOps")
    image_module.MAX_IMAGE_PIXELS = 24_000_000
    with image_module.open(source) as original:
        if original.width * original.height > 24_000_000 or getattr(original, "n_frames", 1) != 1:
            raise ValueError("image_limit")
        oriented = image_ops.exif_transpose(original).convert("RGB")
        normalized = source.with_suffix(".png")
        oriented.save(normalized)
        width, height = oriented.size
    executable = config["executable"]
    version = subprocess.run(
        [executable, "--version"], capture_output=True, check=True, timeout=10, text=True
    ).stdout.splitlines()[0][:200]
    if not version.startswith("tesseract 5."):
        raise ValueError("engine_version")
    output = source.parent / "ocr"
    subprocess.run(
        [
            executable,
            str(normalized),
            str(output),
            "--tessdata-dir",
            config["model_dir"],
            "-l",
            "eng" if config["language"] == "en" else "chi_sim+eng",
            "--psm",
            "3",
            "tsv",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
        timeout=110,
    )
    tsv = output.with_suffix(".tsv")
    if tsv.stat().st_size > 4 * 1024**2:
        raise ValueError("output_limit")
    parts: list[dict[str, Any]] = []
    lines: list[str] = []
    previous: tuple[str, ...] | None = None
    with tsv.open(encoding="utf-8") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            word = row.get("text", "").strip()
            if row.get("level") != "5" or not word:
                continue
            confidence = float(row["conf"])
            if not math.isfinite(confidence):
                raise ValueError("invalid_output")
            key = tuple(row[k] for k in ("page_num", "block_num", "par_num", "line_num"))
            if key != previous:
                lines.append(word)
            else:
                lines[-1] += " " + word
            previous = key
            parts.append(
                {
                    "text": word,
                    "confidence": confidence,
                    "uncertain": confidence < 80,
                    "box": [int(row[k]) for k in ("left", "top", "width", "height")],
                }
            )
            if len(parts) > MAX_PARTS or sum(map(len, lines)) + len(lines) > MAX_TEXT:
                raise ValueError("output_limit")
    return {
        "text": "\n".join(lines),
        "parts": parts,
        "engine": version,
        "image_width": width,
        "image_height": height,
        "coordinate_space": "exif_oriented_pixels",
        "language": config["language"],
        "warnings": [
            "文字顺序、数字、单位和编号仍须对照原照片核对；低分词已标注，分数不是正确率。"
        ],
    }


def speech(source: Path, config: dict[str, Any]) -> dict[str, Any]:
    av = importlib.import_module("av")
    # Decode incrementally with a hard duration/sample cap, before allocating a whole waveform.
    with av.open(str(source)) as container:
        streams = list(container.streams.audio)
        if len(streams) != 1:
            raise ValueError("audio_streams")
        duration = 0.0
        for frame in container.decode(streams[0]):
            if not frame.sample_rate:
                raise ValueError("invalid_audio")
            duration += frame.samples / frame.sample_rate
            if duration > MAX_AUDIO_SECONDS:
                raise ValueError("audio_limit")
    whisper = importlib.import_module("faster_whisper")
    model = whisper.WhisperModel(
        config["model_dir"],
        device="cpu",
        compute_type="int8",
        cpu_threads=2,
        num_workers=1,
        local_files_only=True,
    )
    segments, info = model.transcribe(
        str(source),
        language=None if config["language"] == "auto" else config["language"],
        task="transcribe",
        beam_size=5,
        condition_on_previous_text=False,
        vad_filter=True,
        word_timestamps=False,
    )
    parts: list[dict[str, Any]] = []
    length = 0
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        values = [segment.start, segment.end, segment.avg_logprob, segment.no_speech_prob]
        if not all(math.isfinite(v) for v in values):
            raise ValueError("invalid_output")
        length += len(text) + 1
        if len(parts) >= MAX_PARTS or length > MAX_TEXT:
            raise ValueError("output_limit")
        parts.append(
            {
                "text": text,
                "start_seconds": segment.start,
                "end_seconds": segment.end,
                "avg_logprob": segment.avg_logprob,
                "no_speech_prob": segment.no_speech_prob,
                "uncertain": segment.avg_logprob < -1 or segment.no_speech_prob > 0.6,
            }
        )
    return {
        "text": "\n".join(p["text"] for p in parts),
        "parts": parts,
        "engine": "faster-whisper " + importlib.metadata.version("faster-whisper"),
        "language": info.language,
        "duration_seconds": duration,
        "warnings": [
            "转写可能漏字或在静音、噪声处产生多余文字；时间段和低可信提示仅供回听，不识别说话人。"
        ],
    }


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--fingerprint":
        print(fingerprint(Path(sys.argv[2])))
        return
    signal.alarm(310)
    source, config_path, target = map(Path, sys.argv[1:])
    result: dict[str, Any]
    try:
        config = json.loads(config_path.read_text())
        result = {"result": recognize(source, config)}
    except Exception as error:
        # Never expose original text, filesystem paths or library tracebacks in normal logs.
        code = str(error) if isinstance(error, ValueError) else "engine_failed"
        result = {
            "error": code
            if code
            in {
                "model_unavailable",
                "model_changed",
                "image_limit",
                "engine_version",
                "output_limit",
                "invalid_output",
                "audio_streams",
                "invalid_audio",
                "audio_limit",
            }
            else "engine_failed"
        }
    target.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
