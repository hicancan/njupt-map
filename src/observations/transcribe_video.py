"""Optional Qwen3-ASR worker for local observation audio, not source truth.

Run with an existing isolated qwen-asr environment; this is not a dependency of
map/Blender engineering. Input WAV and machine transcript remain under build/.
Chunk boundaries locate speech approximately, not word-level alignment.
"""
from __future__ import annotations

import argparse
import json
import hashlib
from pathlib import Path


def resume_document(audio: Path, output: Path, model: str, chunk_seconds: int) -> dict:
    digest = hashlib.sha256()
    with audio.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    identity = {"audio_sha256": digest.hexdigest(), "model": model, "chunk_seconds": chunk_seconds}
    if output.is_file():
        document = json.loads(output.read_text(encoding="utf-8"))
        if any(document.get(key) != value for key, value in identity.items()):
            raise ValueError("Existing transcript input, model or chunk length differs")
        return document
    return {**identity, "language": "Chinese", "method": f"{chunk_seconds}s waveform chunks, no forced alignment",
            "status": "unverified_machine_transcript", "segments": []}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", default="Qwen/Qwen3-ASR-1.7B")
    parser.add_argument("--chunk-seconds", type=int, default=30)
    args = parser.parse_args()
    if args.chunk_seconds <= 0 or args.chunk_seconds > 180:
        parser.error("Chunks must be 1–180 seconds")
    document = resume_document(args.audio, args.output, args.model, args.chunk_seconds)
    if document.get("decode_complete"):
        print(json.dumps({"decode_complete": True, "segments": len(document["segments"])}))
        return
    # Import only in the external ASR runtime, never during source validation.
    import soundfile as sf
    import torch
    from qwen_asr import Qwen3ASRModel
    waveform, rate = sf.read(args.audio, dtype="float32")
    if rate != 16000 or waveform.ndim != 1:
        parser.error("Expected mono 16 kHz WAV from FFmpeg")
    model = Qwen3ASRModel.from_pretrained(
        args.model, dtype=torch.bfloat16, device_map="cuda:0",
        max_inference_batch_size=1, max_new_tokens=1024,
    )
    completed = {round(s["start_seconds"] * rate) for s in document["segments"]}
    step = args.chunk_seconds * rate
    for first in range(0, len(waveform), step):
        if first in completed:
            continue
        last = min(first + step, len(waveform))
        result = model.transcribe(audio=(waveform[first:last], rate), language="Chinese")[0]
        segment = {"start_seconds": first / rate, "end_seconds": last / rate, "text": result.text}
        document["segments"].append(segment)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(".tmp")
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(args.output)
        print(json.dumps(segment, ensure_ascii=False), flush=True)
    document["decode_complete"] = True
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
