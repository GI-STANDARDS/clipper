import re
import subprocess
from pathlib import Path

from moviepy import VideoFileClip
from proglog import TqdmProgressBarLogger
from tqdm import tqdm


def parse_timecsv(csv_path: str) -> list[tuple[float, float, str]]:
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    timestamps = []
    pattern = re.compile(
        r"(?:\d+\.\s*)?(\d{1,2}):(\d{2})\s*[\-\u2013\u2014]\s*(\d{1,2}):(\d{2})"
    )

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = pattern.search(line)
            if not m:
                print(f"  [SKIP] Could not parse: {line}")
                continue

            h1, m1, h2, m2 = m.groups()
            start = int(h1) * 60 + int(m1)
            end = int(h2) * 60 + int(m2)
            label = f"{int(h1)}m{int(m1):02d}s-{int(h2)}m{int(m2):02d}s"
            timestamps.append((start, end, label))

    if not timestamps:
        raise ValueError(f"No valid timestamps found in {csv_path}")

    return timestamps


def _seconds_to_ts(s: float) -> str:
    h = int(s) // 3600
    m = (int(s) % 3600) // 60
    sec = int(s) % 60
    if h > 0:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def clip_with_ffmpeg(
    video_path: str,
    timestamps: list[tuple[float, float, str]],
    output_dir: str,
) -> list[str]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    video_path = str(Path(video_path).resolve())

    clips = []
    pbar = tqdm(total=len(timestamps), desc="Clipping", unit="clip", position=0)

    for i, (start, end, label) in enumerate(timestamps, 1):
        out_path = str(output_dir / f"clip_{i:02d}_{label}.mp4")
        ts_start = _seconds_to_ts(start)
        duration = end - start

        cmd = [
            "ffmpeg", "-y",
            "-ss", ts_start,
            "-i", video_path,
            "-t", str(duration),
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            out_path,
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"  [ERROR] Clip {i} failed: {result.stderr[-200:]}")
            continue

        clips.append(out_path)
        pbar.update(1)

    pbar.close()
    return clips


def clip_timestamps(
    video_path: str,
    timestamps: list[tuple[float, float, str]],
    output_dir: str,
) -> list[str]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    video = VideoFileClip(str(video_path))
    duration = video.duration

    clips = []
    pbar = tqdm(total=len(timestamps), desc="Clipping", unit="clip", position=0)

    for i, (start, end, label) in enumerate(timestamps, 1):
        if start >= duration:
            print(f"  [SKIP] Clip {i} start {start}s exceeds video duration {duration:.0f}s")
            continue
        if end > duration:
            print(f"  [WARN] Clip {i} end {end}s exceeds video duration, trimming to {duration:.0f}s")
            end = duration

        subclip = video.subclipped(start, end)
        out_path = str(output_dir / f"clip_{i:02d}_{label}.mp4")
        temp_audio = str(output_dir / f"_temp_audio_{i}.m4a")

        subclip.write_videofile(
            out_path,
            codec="libx264",
            audio_codec="aac",
            temp_audiofile=temp_audio,
            logger=TqdmProgressBarLogger(
                bars={"frame_index": {"title": f"  Encoding {i}/{len(timestamps)}", "index": -1, "total": None, "message": ""}},
                leave_bars=False,
                print_messages=False,
            ),
            fps=min(30, int(getattr(video, "fps", 30) or 30)),
        )
        clips.append(out_path)
        pbar.update(1)

    pbar.close()
    video.close()
    return clips
