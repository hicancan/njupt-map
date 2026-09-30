"""Finish the campus film from numbered renders and the original stereo score.

Run with project Python; only standard-library modules are required. FFmpeg does
the actual media processing. No shell interpolation and no font redistribution.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TITLE_DIR = ROOT / "projects/blender/presentation/titles"


def stamp(seconds: float) -> str:
    centiseconds = round(seconds * 100)
    return f"{centiseconds // 360000}:{centiseconds // 6000 % 60:02}:{centiseconds // 100 % 60:02}.{centiseconds % 100:02}"


def make_titles(duration: float = 35.0, clean: bool = False) -> Path:
    """Create a typography-only overlay in 1920x1080 design coordinates.

    Clean removes the promotional titles. Source-map attribution is visible in
    the closing shot; full project provenance lives in the accompanying docs.
    """
    output_dir = ROOT / 'build/media/titles'
    output_dir.mkdir(parents=True, exist_ok=True)
    out = output_dir / ("campus_clean.ass" if clean else "campus_promo.ass")
    lines = [
        "[Script Info]", "Title: NJUPT Xianlin campus film", "ScriptType: v4.00+",
        "PlayResX: 1920", "PlayResY: 1080", "WrapStyle: 2",
        "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Hero,Segoe UI Light,78,&H00F7F5F0,&H00FFFFFF,&H800E1012,&H8A000000,0,0,0,0,100,100,2,0,1,0.7,1.2,7,110,110,70,1",
        "Style: Sub,Microsoft YaHei,24,&H00EEE5CE,&H00FFFFFF,&H700A0C10,&HA0000000,0,0,0,0,100,100,2,0,1,0.6,0.8,7,110,110,70,1",
        "Style: English,Segoe UI,20,&H00E5DACA,&H00FFFFFF,&H800A0C10,&HA0000000,0,0,0,0,100,100,3.2,0,1,0.5,0.8,7,110,110,70,1",
        "Style: Credit,Microsoft YaHei,17,&H16EDE9E1,&H00FFFFFF,&H500A0C10,&H80000000,0,0,0,0,100,100,0,0,1,0.6,1,1,110,110,45,1",
        "Style: Rule,Arial,20,&H00C7B48B,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    def event(start, end, style, content, layer=1):
        lines.append(f"Dialogue: {layer},{stamp(start)},{stamp(end)},{style},,0,0,0,,{content}")

    end = max(0.0, duration - 0.8)
    event(max(0.7, duration - 4.5), end, "Credit", r"{\fad(500,350)}Map data © OpenStreetMap contributors · ODbL")
    if not clean:
        event(0.85, min(4.65, end), "Rule", r"{\pos(112,820)\fad(550,450)\p1}m 0 0 l 76 0 76 3 0 3{\p0}", 0)
        event(1.05, min(4.65, end), "Hero", r"{\move(108,829,108,815,0,1100)\fad(650,450)}njupt-map")
        event(1.28, min(4.65, end), "Sub", r"{\pos(112,922)\fad(600,450)}南京邮电大学 · 仙林校区")
        event(1.42, min(4.65, end), "English", r"{\pos(112,966)\fad(600,450)}A NEW PERSPECTIVE")
        if duration >= 30:
            start = duration - 4.5
            event(start, end, "Rule", r"{\pos(112,733)\fad(550,450)\p1}m 0 0 l 76 0 76 3 0 3{\p0}", 0)
            event(start + 0.15, end, "Hero", r"{\move(108,747,108,734,0,1100)\fad(650,450)}njupt-map")
            event(start + 0.38, end, "Sub", r"{\pos(112,849)\fad(600,450)}南京邮电大学 · 仙林校区")
            event(start + 0.6, end, "English", r"{\pos(112,894)\fad(550,450)}A NEW PERSPECTIVE")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return out


def filter_path(path: Path) -> str:
    """Escape a path as a single FFmpeg filter argument, not shell quoting."""
    # C:\foo becomes C\:/foo; apostrophes need leaving and reentering the
    # filter's quoted value. subprocess still receives one argv item.
    return path.resolve().as_posix().replace(":", r"\:").replace("'", r"'\''")


def check_frames(pattern: str, start: int, count: int) -> None:
    if not re.search(r"%0?\d*d", pattern):
        raise ValueError("Input pattern must contain an integer placeholder, e.g. frame_%04d.png")
    missing = []
    for index in range(start, start + count):
        if not Path(pattern % index).is_file():
            missing.append(index)
    if missing:
        raise FileNotFoundError(f"Missing {len(missing)} source frames; first indices: {missing[:12]}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-pattern", default=str(ROOT / "build/blender/renders/film/frames/frame_%04d.png"))
    parser.add_argument("--wav", type=Path, help="Original stereo soundtrack")
    parser.add_argument("--output", type=Path, default=ROOT / "build/media/njupt-map.mp4")
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--duration", type=float, default=35.0)
    parser.add_argument("--start-number", type=int, default=1)
    parser.add_argument("--clean", action="store_true", help="Omit promotional titles; retain the closing map attribution")
    parser.add_argument("--crf", type=int, default=17)
    parser.add_argument("--preset", default="slow")
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    parser.add_argument("--titles-only", action="store_true")
    parser.add_argument("--generate-titles", action="store_true", help="Generate candidate titles in build/ instead of using the authored source")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--smoke-test", action="store_true", help="Use a generated color source, no campus frames/GPU needed")
    args = parser.parse_args()
    if args.duration <= 1 or args.fps <= 0:
        raise ValueError("Duration must exceed 1 second and fps must be positive")
    total_frames = round(args.duration * args.fps)
    subtitle = (make_titles(args.duration, args.clean) if args.generate_titles else
                TITLE_DIR / ('campus_clean.ass' if args.clean else 'campus_promo.ass'))
    if not subtitle.is_file():
        raise FileNotFoundError(subtitle)
    if args.titles_only:
        print(subtitle)
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    command = [args.ffmpeg, "-hide_banner", "-y"]
    if args.smoke_test:
        command += ["-f", "lavfi", "-i", f"color=c=0x233946:size=1920x1080:rate={args.fps}:duration={args.duration}"]
    else:
        if not args.dry_run:
            check_frames(args.input_pattern, args.start_number, total_frames)
        command += ["-framerate", str(args.fps), "-start_number", str(args.start_number), "-i", args.input_pattern]
    if args.wav:
        if not args.wav.is_file():
            raise FileNotFoundError(args.wav)
        command += ["-i", str(args.wav)]
    elif not args.smoke_test:
        raise ValueError("Provide --wav for the finished film (or use --smoke-test)")
    fade_out = max(0, args.duration - 1)
    # Source PNGs are already Blender AgX display-referred. Keep the additional
    # grade subtle; a strong LUT would double-tone-map and clip the white facades.
    filters = [
        "scale=1920:1080:flags=lanczos:out_color_matrix=bt709:out_range=tv", "setsar=1",
        "eq=contrast=1.015:saturation=1.035:brightness=-0.002",
        f"ass=filename='{filter_path(subtitle)}'",
        "fade=t=in:st=0:d=0.5", f"fade=t=out:st={fade_out:g}:d=1",
        "format=yuv420p",
    ]
    command += ["-map", "0:v:0", "-vf", ",".join(filters)]
    if args.wav:
        # The original score is mastered upstream; do not loudness-normalize it
        # again. Tiny input and final safety fades prevent edit-boundary clicks.
        command += ["-map", "1:a:0", "-af", f"afade=t=in:st=0:d=0.08,afade=t=out:st={args.duration - 0.45:g}:d=0.45,apad",
                    "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-ac", "2"]
    command += ["-c:v", "libx264", "-preset", args.preset, "-crf", str(args.crf),
                "-profile:v", "high", "-level:v", "4.1", "-r", str(args.fps),
                "-frames:v", str(total_frames), "-t", str(args.duration),
                "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                "-movflags", "+faststart", "-metadata", "title=njupt-map · 南京邮电大学仙林校区",
                "-metadata", "comment=njupt-map campus project. Map data © OpenStreetMap contributors, ODbL.",
                str(args.output)]
    report = {
        "command": command, "source_pattern": args.input_pattern, "fps": args.fps,
        "frame_count": total_frames, "duration_seconds": args.duration,
        "subtitle_file": str(subtitle), "clean": args.clean,
        "font_policy": "Uses installed Windows fonts to rasterize titles; font files are not distributed.",
        "color": "Blender AgX rendered PNG -> very light saturation/contrast grade -> BT.709 tags, yuv420p",
        "output": str(args.output), "soundtrack": str(args.wav) if args.wav else None,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.dry_run:
        return
    subprocess.run(command, check=True)
    probe = shutil.which("ffprobe")
    if probe:
        result = subprocess.run([probe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(args.output)],
                                check=True, capture_output=True, text=True, encoding="utf-8")
        report["ffprobe"] = json.loads(result.stdout)
    report["status"] = "encoded"
    args.output.with_suffix(".encoding.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"Film finishing failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
