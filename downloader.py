import json
import re
import struct
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests
import yt_dlp

from clipper import parse_timecsv


_YTDL_COMMON = {
    "js_runtimes": {"node": {}},
    "remote_components": {"ejs:github"},
}


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:120] if name else "video"


def get_video_info(url: str) -> dict:
    opts = {
        **_YTDL_COMMON,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return {
        "title": info.get("title", "video"),
        "duration": info.get("duration", 0),
    }


def fetch_formats(url: str) -> tuple[list[dict], str, int]:
    opts = {
        **_YTDL_COMMON,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    title = info.get("title", "video")
    total_duration = info.get("duration", 0) or 1

    formats = []
    seen_res = {}
    for f in info.get("formats", []):
        if f.get("vcodec") == "none":
            continue
        fmt_id = f.get("format_id", "")
        ext = f.get("ext", "")
        w = f.get("width") or 0
        h = f.get("height") or 0
        if w == 0 or h == 0:
            continue
        has_audio = f.get("acodec", "none") != "none"
        filesize = f.get("filesize") or f.get("filesize_approx") or 0
        res_key = f"{h}p"

        if res_key in seen_res:
            existing = seen_res[res_key]
            if has_audio and not existing["has_audio"]:
                seen_res[res_key] = {
                    "id": fmt_id,
                    "ext": ext,
                    "resolution": f"{w}x{h}",
                    "width": w,
                    "height": h,
                    "filesize": filesize,
                    "has_audio": has_audio,
                }
            elif has_audio == existing["has_audio"] and filesize > existing["filesize"]:
                seen_res[res_key] = {
                    "id": fmt_id,
                    "ext": ext,
                    "resolution": f"{w}x{h}",
                    "width": w,
                    "height": h,
                    "filesize": filesize,
                    "has_audio": has_audio,
                }
        else:
            seen_res[res_key] = {
                "id": fmt_id,
                "ext": ext,
                "resolution": f"{w}x{h}",
                "width": w,
                "height": h,
                "filesize": filesize,
                "has_audio": has_audio,
            }

    formats = list(seen_res.values())
    formats.sort(key=lambda x: x["height"], reverse=True)
    return formats, title, total_duration


def format_size(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "?"
    mb = size_bytes / 1024 / 1024
    if mb >= 1024:
        return f"~{mb / 1024:.1f}GB"
    return f"~{mb:.0f}MB"


def estimate_clip_sizes(
    timestamps: list[tuple[float, float, str]],
    total_duration: int,
    total_filesize: int,
) -> list[tuple[str, int, str]]:
    results = []
    for start, end, label in timestamps:
        clip_dur = end - start
        if total_duration > 0 and total_filesize > 0:
            est = int((clip_dur / total_duration) * total_filesize)
        else:
            est = 0
        results.append((label, clip_dur, format_size(est)))
    return results


def check_cached_source(output_dir: str) -> Path | None:
    temp_dir = Path(output_dir) / "_temp"
    if not temp_dir.exists():
        return None

    for p in temp_dir.iterdir():
        if p.name.endswith(".part"):
            p.unlink(missing_ok=True)

    for ext in ("mp4", "webm", "mkv"):
        source = temp_dir / f"source.{ext}"
        if source.exists() and source.stat().st_size > 0:
            return source
    return None


def _fmt_ts(s: float) -> str:
    h = int(s) // 3600
    m = (int(s) % 3600) // 60
    sec = int(s) % 60
    if h > 0:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def _get_format_info_from_ytdlp(url: str, format_id: str) -> dict:
    opts = {
        **_YTDL_COMMON,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "format": format_id,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    rf = info.get("requested_formats", [])
    if rf:
        video_fmt = next((f for f in rf if f.get("vcodec", "none") != "none"), rf[0])
        audio_fmt = next((f for f in rf if f.get("acodec", "none") != "none" and f.get("vcodec") == "none"), None)
    else:
        video_fmt = info
        audio_fmt = None

    return {
        "url": video_fmt.get("url", ""),
        "filesize": video_fmt.get("filesize") or video_fmt.get("filesize_approx") or 0,
        "http_headers": video_fmt.get("http_headers", {}),
        "duration": info.get("duration", 0) or 0,
        "audio_url": audio_fmt.get("url", "") if audio_fmt else "",
        "audio_headers": audio_fmt.get("http_headers", {}) if audio_fmt else {},
        "audio_filesize": audio_fmt.get("filesize") or audio_fmt.get("filesize_approx") or 0 if audio_fmt else 0,
    }


# ============================================================================
# LAYER 1: Segment-Aware Download (best effort)
# ============================================================================

def _extract_page_init_index(url: str, format_id: str) -> dict | None:
    print("  [L1] Fetching YouTube page for adaptiveFormats...", flush=True)
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"  [L1] Page fetch failed: {e}", flush=True)
        return None

    m = re.search(r'var ytInitialPlayerResponse\s*=\s*(\{.*?\});', resp.text)
    if not m:
        m = re.search(r'ytInitialPlayerResponse\s*=\s*(\{.*?\});', resp.text)
    if not m:
        print("  [L1] Could not find ytInitialPlayerResponse in page", flush=True)
        return None

    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        print(f"  [L1] JSON parse failed: {e}", flush=True)
        return None

    formats = data.get("streamingData", {}).get("adaptiveFormats", [])
    print(f"  [L1] Found {len(formats)} adaptive formats in page", flush=True)

    target_itag = format_id.lstrip("-")
    matched = None
    for f in formats:
        if str(f.get("itag")) == target_itag:
            matched = f
            break

    if not matched:
        print(f"  [L1] itag {target_itag} not found in adaptiveFormats", flush=True)
        return None

    init_range = matched.get("initRange")
    index_range = matched.get("indexRange")
    content_length = matched.get("contentLength")

    if not init_range or not index_range:
        print(f"  [L1] initRange or indexRange missing for itag {target_itag}", flush=True)
        return None

    if not content_length:
        print(f"  [L1] contentLength missing for itag {target_itag}", flush=True)
        return None

    init_start = int(init_range.get("start", "0"))
    init_end = int(init_range.get("end", "0"))
    index_start = int(index_range.get("start", "0"))
    index_end = int(index_range.get("end", "0"))

    print(f"  [L1] Matched itag {target_itag} ({matched.get('width')}x{matched.get('height')})", flush=True)
    print(f"  [L1] initRange: {init_start}-{init_end} ({init_end - init_start + 1} bytes)", flush=True)
    print(f"  [L1] indexRange: {index_start}-{index_end} ({index_end - index_start + 1} bytes)", flush=True)

    return {
        "init_start": init_start,
        "init_end": init_end,
        "index_start": index_start,
        "index_end": index_end,
        "content_length": int(content_length),
        "bitrate": matched.get("bitrate", 0),
        "mimeType": matched.get("mimeType", ""),
        "duration_ms": int(matched.get("approxDurationMs", 0)),
    }


def _detect_indexing_type(index_bytes: bytes) -> str:
    if len(index_bytes) < 8:
        print("  [L1] Index data too short to detect type", flush=True)
        return "unknown"

    box_size = struct.unpack(">I", index_bytes[0:4])[0]
    box_type = index_bytes[4:8].decode("ascii", errors="replace")

    print(f"  [L1] Index box: type={box_type}, size={box_size}", flush=True)

    if box_type == "sidx":
        return "sidx"
    elif box_type == "styp":
        return "styp"
    elif box_type == "moof":
        return "fragmented"
    else:
        return "unknown"


def _parse_sidx(data: bytes) -> tuple[list[dict], int]:
    if len(data) < 8:
        raise ValueError("sidx data too short")

    box_size = struct.unpack(">I", data[0:4])[0]
    box_type = data[4:8].decode("ascii", errors="replace")

    if box_type != "sidx":
        raise ValueError(f"Unsupported box type: {box_type}")

    offset = 8
    version = data[offset]
    offset += 1
    offset += 3  # flags

    reference_id = struct.unpack(">I", data[offset:offset + 4])[0]
    offset += 4
    timescale = struct.unpack(">I", data[offset:offset + 4])[0]
    offset += 4

    if version == 0:
        earliest_pt = struct.unpack(">I", data[offset:offset + 4])[0]
        offset += 4
        first_offset = struct.unpack(">I", data[offset:offset + 4])[0]
        offset += 4
    else:
        earliest_pt = struct.unpack(">Q", data[offset:offset + 8])[0]
        offset += 8
        first_offset = struct.unpack(">Q", data[offset:offset + 8])[0]
        offset += 8

    ref_count = struct.unpack(">H", data[offset:offset + 2])[0]
    offset += 2

    if ref_count == 0:
        for try_offset in [offset, offset + 2]:
            remaining = box_size - try_offset
            if remaining > 0 and remaining % 12 == 0:
                ref_count = remaining // 12
                offset = try_offset
                print(f"  [L1] sidx: ref_count was 0 at {try_offset - 2}, recalculated: {ref_count} (at offset {try_offset})", flush=True)
                break

    print(f"  [L1] sidx: timescale={timescale}, references={ref_count}, header_used={offset}", flush=True)

    segments = []
    byte_offset = first_offset
    for i in range(ref_count):
        if offset + 12 > len(data):
            print(f"  [L1] Warning: not enough data for segment {i} (have {len(data) - offset} bytes, need 12)", flush=True)
            break

        ref_word = struct.unpack(">I", data[offset:offset + 4])[0]
        offset += 4
        segment_duration = struct.unpack(">I", data[offset:offset + 4])[0]
        offset += 4
        sap_word = struct.unpack(">I", data[offset:offset + 4])[0]
        offset += 4

        ref_size = ref_word & 0x7FFFFFFF
        duration_sec = segment_duration / timescale if timescale > 0 else 0

        segments.append({
            "offset": byte_offset,
            "size": ref_size,
            "duration_sec": duration_sec,
            "duration_ticks": segment_duration,
        })
        byte_offset += ref_size

    total_dur = sum(s["duration_sec"] for s in segments)
    print(f"  [L1] Parsed {len(segments)} segments, total duration={total_dur:.1f}s", flush=True)
    if segments:
        print(f"  [L1] First segment: offset={segments[0]['offset']}, size={segments[0]['size']}, dur={segments[0]['duration_sec']:.2f}s", flush=True)

    return segments, timescale


def _map_timestamps_to_segments(
    timestamps: list[tuple[float, float, str]],
    segments: list[dict],
    timescale: int,
    init_end: int,
) -> list[dict]:
    cumulative = 0.0
    seg_times = []
    for seg in segments:
        seg_times.append({"start": cumulative, "end": cumulative + seg["duration_sec"], "size": seg["size"], "offset": seg["offset"]})
        cumulative += seg["duration_sec"]

    print(f"  [L1] Segment timeline: {len(segments)} segments, {cumulative:.1f}s total", flush=True)

    result = []
    for i, (start, end, label) in enumerate(timestamps):
        start_seg = 0
        end_seg = len(segments) - 1

        for j, st in enumerate(seg_times):
            if st["end"] >= start:
                start_seg = j
                break

        for j in range(start_seg, len(seg_times)):
            if seg_times[j]["start"] >= end:
                end_seg = j
                break
        else:
            end_seg = len(segments) - 1

        byte_start = init_end + 1 + segments[start_seg]["offset"]
        byte_end = init_end + 1 + segments[end_seg]["offset"] + segments[end_seg]["size"] - 1
        total_bytes = byte_end - byte_start + 1

        print(f"  [L1] Clip {i+1} ({label}): {start:.0f}s-{end:.0f}s -> segments {start_seg}-{end_seg} ({end_seg - start_seg + 1} segs, ~{total_bytes / 1024 / 1024:.1f} MB)", flush=True)

        result.append({
            "clip_idx": i,
            "start": start,
            "end": end,
            "label": label,
            "start_seg": start_seg,
            "end_seg": end_seg,
            "byte_start": byte_start,
            "byte_end": byte_end,
        })

    return result


def _range_download(url: str, headers: dict, start: int, end: int) -> bytes:
    range_headers = {**headers, "Range": f"bytes={start}-{end}"}
    resp = requests.get(url, headers=range_headers, timeout=30)
    resp.raise_for_status()
    return resp.content


def _download_clips_via_segments(
    url: str,
    timestamps: list[tuple[float, float, str]],
    out: Path,
    title: str,
    format_id: str,
    height: int,
) -> tuple[list[str], str]:
    from clipper import clip_with_ffmpeg

    page_data = _extract_page_init_index(url, format_id)
    if not page_data:
        raise RuntimeError("Could not extract page format data")

    fmt_info = _get_format_info_from_ytdlp(url, format_id)
    direct_url = fmt_info["url"]
    headers = fmt_info["http_headers"]

    if not direct_url:
        raise RuntimeError("No direct URL from yt-dlp")

    print(f"  [L1] Downloading init segment...", flush=True)
    init_bytes = _range_download(direct_url, headers, page_data["init_start"], page_data["init_end"])
    print(f"  [L1] Init segment: {len(init_bytes)} bytes", flush=True)

    print(f"  [L1] Downloading index segment...", flush=True)
    index_bytes = _range_download(direct_url, headers, page_data["index_start"], page_data["index_end"])
    print(f"  [L1] Index segment: {len(index_bytes)} bytes", flush=True)

    indexing_type = _detect_indexing_type(index_bytes)

    if indexing_type != "sidx":
        raise RuntimeError(f"Unsupported indexing type: {indexing_type} (only sidx supported)")

    segments, timescale = _parse_sidx(index_bytes)
    if not segments:
        raise RuntimeError("No segments found in sidx")

    clip_mappings = _map_timestamps_to_segments(timestamps, segments, timescale, page_data["init_end"])

    print(f"  [L1] Downloading audio (full track)...", flush=True)
    audio_url = fmt_info.get("audio_url", "")
    audio_headers = fmt_info.get("audio_headers", {})
    audio_file = out / "audio.webm"
    if audio_url:
        audio_resp = requests.get(audio_url, headers=audio_headers, timeout=300, stream=True)
        audio_resp.raise_for_status()
        with open(audio_file, "wb") as f:
            for chunk in audio_resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
        print(f"  [L1] Audio: {audio_file.stat().st_size / 1024 / 1024:.1f} MB", flush=True)
    else:
        audio_file = None
        print(f"  [L1] No audio URL available", flush=True)

    clips = []
    total = len(clip_mappings)

    init_end = page_data["init_end"]

    max_seg_idx = max(m["end_seg"] for m in clip_mappings)
    contiguous_end = init_end + 1
    for si in range(max_seg_idx + 1):
        contiguous_end += segments[si]["size"]

    print(f"  [L1] Downloading video: byte 0 to {contiguous_end} ({contiguous_end / 1024 / 1024:.1f} MB)...", flush=True)
    try:
        source_resp = requests.get(direct_url, headers={**headers, "Range": f"bytes=0-{contiguous_end - 1}"}, timeout=600, stream=True)
        source_resp.raise_for_status()
        source_file = out / "source_l1.mp4"
        with open(source_file, "wb") as f:
            for chunk in source_resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
        print(f"  [L1] Source: {source_file.stat().st_size / 1024 / 1024:.1f} MB", flush=True)
    except Exception as e:
        raise RuntimeError(f"Video download failed: {e}")

    print(f"  [L1] Clipping {len(timestamps)} segments (ffmpeg -c copy)...", flush=True)
    clips = clip_with_ffmpeg(str(source_file), timestamps, str(out))

    source_file.unlink(missing_ok=True)

    return clips, title


# ============================================================================
# LAYER 2: Range Request + Estimation (reliable)
# ============================================================================

def _range_download_estimated(
    url: str,
    timestamps: list[tuple[float, float, str]],
    out: Path,
    title: str,
    format_id: str,
    height: int,
) -> tuple[list[str], str]:
    from clipper import clip_with_ffmpeg

    fmt_info = _get_format_info_from_ytdlp(url, format_id)
    direct_url = fmt_info["url"]
    headers = fmt_info["http_headers"]
    filesize = fmt_info["filesize"]
    duration = fmt_info["duration"]

    if not direct_url:
        raise RuntimeError("No direct URL from yt-dlp")
    if filesize <= 0:
        raise RuntimeError("Unknown filesize, cannot estimate byte ranges")
    if duration <= 0:
        raise RuntimeError("Unknown duration, cannot estimate byte ranges")

    print(f"  [L2] Direct URL obtained, filesize={filesize / 1024 / 1024:.1f}MB, duration={duration:.0f}s", flush=True)

    last_clip_end = max(end for _, end, _ in timestamps)
    end_byte = min(filesize - 1, int(last_clip_end * (filesize / duration)) + int(filesize / duration * 5))
    end_mb = end_byte / 1024 / 1024
    full_mb = filesize / 1024 / 1024
    print(f"  [L2] Downloading video from byte 0 to {end_byte} ({end_mb:.1f}MB of {full_mb:.1f}MB)", flush=True)

    try:
        video_resp = requests.get(direct_url, headers={**headers, "Range": f"bytes=0-{end_byte}"}, timeout=600, stream=True)
        video_resp.raise_for_status()
        source_file = out / "source_l2.mp4"
        with open(source_file, "wb") as f:
            for chunk in video_resp.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
        source_mb = source_file.stat().st_size / 1024 / 1024
        print(f"  [L2] Video source: {source_mb:.1f} MB", flush=True)
    except Exception as e:
        raise RuntimeError(f"Video download failed: {e}")

    print(f"  [L2] Clipping {len(timestamps)} segments (ffmpeg -c copy)...", flush=True)
    clips = clip_with_ffmpeg(str(source_file), timestamps, str(out))

    source_file.unlink(missing_ok=True)

    return clips, title


# ============================================================================
# EXISTING PATHS (unchanged)
# ============================================================================

def download_clips_directly(
    url: str,
    timestamps: list[tuple[float, float, str]],
    output_dir: str,
    format_id: str | None = None,
    has_audio: bool = True,
    height: int = 0,
) -> tuple[list[str], str]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    print("  Resolving video info...", flush=True)
    info = get_video_info(url)
    title = sanitize_filename(info["title"])

    if has_audio or not format_id:
        fmt = format_id if format_id else "best[ext=mp4]/best"
        return _download_segments(url, timestamps, out, title, fmt)
    else:
        print(f"  DASH format {format_id} selected (video-only)", flush=True)
        print()

        print("  [LAYER 1] Trying segment-aware download...", flush=True)
        try:
            result = _download_clips_via_segments(url, timestamps, out, title, format_id, height)
            if result[0]:
                print("  [LAYER 1] SUCCESS", flush=True)
                return result
            print("  [LAYER 1] No clips produced, falling through...", flush=True)
        except Exception as e:
            print(f"  [LAYER 1] FAILED: {e}", flush=True)
            print("  [LAYER 1] Falling through to Layer 2...", flush=True)

        print()
        print("  [LAYER 2] Trying range-request download...", flush=True)
        try:
            result = _range_download_estimated(url, timestamps, out, title, format_id, height)
            if result[0]:
                print("  [LAYER 2] SUCCESS", flush=True)
                return result
            print("  [LAYER 2] No clips produced, falling through...", flush=True)
        except Exception as e:
            print(f"  [LAYER 2] FAILED: {e}", flush=True)
            print("  [LAYER 2] Falling through to Layer 3...", flush=True)

        print()
        print("  [LAYER 3] Falling back to full download + clip...", flush=True)
        return _download_full_then_clip(url, timestamps, out, title, format_id, height)


def _download_segments(
    url: str,
    timestamps: list[tuple[float, float, str]],
    out: Path,
    title: str,
    fmt: str,
) -> tuple[list[str], str]:
    clips = []
    total = len(timestamps)
    for i, (start, end, label) in enumerate(timestamps, 1):
        out_template = str(out / f"clip_{i:02d}_{label}.%(ext)s")
        ts_from = _fmt_ts(start)
        ts_to = _fmt_ts(end)

        print(f"  [{i}/{total}] {ts_from} -> {ts_to} ({label})", flush=True)

        success = False
        for attempt in range(3):
            cmd = [
                "yt-dlp",
                "--js-runtimes", "node",
                "--remote-components", "ejs:github",
                "-f", fmt,
                "--download-sections", f"*{ts_from}-{ts_to}",
                "-o", out_template,
                "--no-force-keyframes-at-cuts",
                "--no-part",
                "--merge-output-format", "mp4",
                "--newline",
                url,
            ]

            result = subprocess.run(cmd, timeout=300)
            clip_file = out / f"clip_{i:02d}_{label}.mp4"
            if result.returncode == 0 and clip_file.exists():
                success = True
                break

            if attempt < 2:
                wait = 10 * (attempt + 1)
                print(f"  [RETRY] Attempt {attempt + 1} failed, waiting {wait}s...", flush=True)
                time.sleep(wait)

        if not success:
            print(f"  [ERROR] Clip {i} failed after 3 attempts")
            continue

        size = clip_file.stat().st_size / 1024 / 1024
        print(f"  [{i}/{total}] Done ({size:.1f} MB)")
        clips.append(str(clip_file))

        if i < total:
            time.sleep(3)

    return clips, title


def _download_full_then_clip(
    url: str,
    timestamps: list[tuple[float, float, str]],
    out: Path,
    title: str,
    format_id: str,
    height: int,
) -> tuple[list[str], str]:
    from clipper import clip_with_ffmpeg

    fmt = f"{format_id}+bestaudio"

    source = None
    for attempt in range(3):
        print(f"  [L3] Downloading source video (attempt {attempt + 1}/3)...", flush=True)

        source_file = str(out / "source.mp4")
        cmd = [
            "yt-dlp",
            "--js-runtimes", "node",
            "--remote-components", "ejs:github",
            "-f", fmt,
            "-o", source_file,
            "--merge-output-format", "mp4",
            "--newline",
            url,
        ]

        result = subprocess.run(cmd, timeout=1800)

        for ext in ("mp4", "webm", "mkv"):
            candidate = out / f"source.{ext}"
            if candidate.exists() and candidate.stat().st_size > 0:
                source = str(candidate)
                break

        if source:
            break

        if attempt < 2:
            wait = 30 * (attempt + 1)
            print(f"  [L3] [RETRY] Waiting {wait}s before retry...", flush=True)
            time.sleep(wait)
            for ext in ("mp4", "webm", "mkv", "part"):
                p = out / f"source.{ext}"
                if p.exists():
                    p.unlink(missing_ok=True)

    if not source:
        print("  [L3] [ERROR] Source download failed after 3 attempts")
        return [], title

    src_size = Path(source).stat().st_size / 1024 / 1024
    print(f"  [L3] Source: {src_size:.0f} MB")
    print(f"  [L3] Clipping {len(timestamps)} segments (ffmpeg -c copy)...")
    print()

    clips = clip_with_ffmpeg(source, timestamps, str(out))

    for ext in ("mp4", "webm", "mkv"):
        p = out / f"source.{ext}"
        if p.exists():
            p.unlink()

    return clips, title


def fetch_playlist_info(url: str) -> dict:
    opts_flat = {
        **_YTDL_COMMON,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlist_items": "0:100",
        "skip_download": True,
    }

    with yt_dlp.YoutubeDL(opts_flat) as ydl:
        info = ydl.extract_info(url, download=False)

    playlist_title = info.get("playlist_title") or info.get("title") or "playlist"
    entries = list(info.get("entries", []))

    videos = []
    for entry in entries:
        if not entry:
            continue
        videos.append({
            "title": entry.get("title") or entry.get("id") or "unknown",
            "id": entry.get("id") or "",
            "duration": entry.get("duration") or 0,
        })

    if not videos:
        return {"title": playlist_title, "videos": [], "resolutions": []}

    sample_count = min(5, len(videos))
    opts_full = {
        **_YTDL_COMMON,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    seen_resolutions = {}

    for vid in videos[:sample_count]:
        vid_url = f"https://www.youtube.com/watch?v={vid['id']}"
        try:
            with yt_dlp.YoutubeDL(opts_full) as ydl:
                vinfo = ydl.extract_info(vid_url, download=False)
        except Exception:
            continue

        formats = vinfo.get("formats") or []
        best_for_height = {}

        for f in formats:
            height = f.get("height")
            if not isinstance(height, int) or height == 0:
                continue
            if f.get("vcodec") == "none":
                continue

            has_audio = f.get("acodec") not in ("none", None, "") and (f.get("abr") or 0) > 0
            filesize = f.get("filesize") or f.get("filesize_approx") or 0
            if not isinstance(filesize, int):
                filesize = 0
            fmt_id = f.get("format_id") or ""

            key = f"{height}p"
            if key not in best_for_height:
                best_for_height[key] = {
                    "height": height,
                    "format_id": fmt_id,
                    "filesize": filesize,
                    "has_audio": has_audio,
                }
            else:
                cur = best_for_height[key]
                if has_audio and not cur["has_audio"]:
                    best_for_height[key] = {
                        "height": height,
                        "format_id": fmt_id,
                        "filesize": filesize,
                        "has_audio": has_audio,
                    }
                elif has_audio == cur["has_audio"] and filesize > cur["filesize"]:
                    best_for_height[key] = {
                        "height": height,
                        "format_id": fmt_id,
                        "filesize": filesize,
                        "has_audio": has_audio,
                    }

        for key, fmt in best_for_height.items():
            if key not in seen_resolutions:
                seen_resolutions[key] = {
                    "height": fmt["height"],
                    "label": key,
                    "total_size": 0,
                    "avg_size": 0,
                    "count": 0,
                    "format_id": fmt["format_id"],
                    "has_audio": fmt["has_audio"],
                }
            seen_resolutions[key]["total_size"] += fmt["filesize"]
            seen_resolutions[key]["count"] += 1
            if fmt["format_id"] and (not seen_resolutions[key]["format_id"] or (fmt["has_audio"] and not seen_resolutions[key]["has_audio"])):
                seen_resolutions[key]["format_id"] = fmt["format_id"]
                seen_resolutions[key]["has_audio"] = fmt["has_audio"]

    resolutions = sorted(seen_resolutions.values(), key=lambda x: -x["height"])
    for r in resolutions:
        if r["count"] > 0:
            avg = r["total_size"] // r["count"]
            r["avg_size"] = avg
            r["total_size"] = avg * len(videos)
        else:
            r["avg_size"] = 0
            r["total_size"] = 0

    return {
        "title": playlist_title,
        "videos": videos,
        "resolutions": resolutions,
    }


def download_playlist_video(
    url: str,
    output_dir: str,
    target_height: int = 0,
    format_id: str | None = None,
    retries: int = 3,
) -> tuple[bool, str]:
    info = get_video_info(url)
    title = sanitize_filename(info.get("title", "video"))
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    if format_id:
        fmt = f"{format_id}+bestaudio/best[height<={target_height}]/best"
    elif target_height > 0:
        fmt = f"bestvideo[height<={target_height}][ext=mp4]+bestaudio[ext=m4a]/best[height<={target_height}]/best[ext=mp4]/best"
    else:
        fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

    opts = {
        **_YTDL_COMMON,
        "outtmpl": str(output_path / f"{title}.%(ext)s"),
        "merge_output_format": "mp4",
        "format": fmt,
        "no_warnings": True,
        "no_part": True,
        "retries": retries,
        "fragment_retries": retries,
        "retry_on_fragments_missing": True,
        "progress_hooks": [lambda d: _print_dl_progress(d, title)],
    }

    for attempt in range(1, retries + 1):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            return True, title
        except Exception as e:
            if attempt < retries:
                wait = attempt * 10
                print(f"    Retry {attempt}/{retries} in {wait}s...")
                time.sleep(wait)
            else:
                print(f"    Failed after {retries} attempts: {e}")
    return False, title


def _print_dl_progress(d, title=""):
    status = d.get("status")
    if status == "downloading":
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        downloaded = d.get("downloaded_bytes") or 0
        speed = d.get("speed")
        eta = d.get("eta")
        if total > 0:
            pct = downloaded / total * 100
            dl_mb = downloaded / 1048576
            total_mb = total / 1048576
            speed_str = f"{speed/1048576:.1f}MB/s" if speed else "?"
            eta_str = f"{eta//60}m{eta%60:02d}s" if eta else "?"
            print(f"    {pct:5.1f}%  {dl_mb:.1f}/{total_mb:.1f}MB  {speed_str}  ETA {eta_str}    ", end="\r", flush=True)
    elif status == "finished":
        print()


def download_video(
    url: str,
    format_id: str | None = None,
    output_dir: str = ".",
) -> tuple[Path, str]:
    temp_dir = Path(output_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    for p in temp_dir.iterdir():
        if p.name.endswith(".part"):
            p.unlink(missing_ok=True)

    cached = check_cached_source(str(temp_dir))
    if cached:
        info = get_video_info(url)
        title = sanitize_filename(info["title"])
        return cached, title

    info = get_video_info(url)
    title = sanitize_filename(info["title"])

    fmt = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
    if format_id:
        fmt = f"{format_id}+bestaudio/best"

    opts = {
        **_YTDL_COMMON,
        "outtmpl": str(temp_dir / "source.%(ext)s"),
        "merge_output_format": "mp4",
        "format": fmt,
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    for ext in ("mp4", "webm", "mkv"):
        candidate = temp_dir / f"source.{ext}"
        if candidate.exists():
            return candidate, title

    raise FileNotFoundError("Download completed but source file not found")
