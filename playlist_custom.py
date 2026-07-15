import re
import sys
import time
from pathlib import Path

import tkinter as tk
from tkinter import filedialog

sys.path.insert(0, str(Path(__file__).parent))
from downloader import (
    _YTDL_COMMON,
    download_playlist_video,
    format_size,
    sanitize_filename,
)
import yt_dlp


def clear_screen():
    import os
    os.system("cls" if os.name == "nt" else "clear")


def extract_episode_number(title):
    patterns = [
        r"(?:ep|episode|ep\.|eps|eps\.)\s*(\d+)",
        r"#\s*(\d+)",
        r"[\[\(]\s*(\d+)\s*[\]\)]",
        r"-\s*(\d+)(?:\s|$|[-\u2013\u2014])",
        r"(?:part|pt)\s*(\d+)",
        r"\b(\d{2,5})\b",
    ]
    for pat in patterns:
        m = re.search(pat, title, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def extract_video_id(url):
    m = re.search(r"(?:v=|/v/|youtu\.be/|embed/|shorts/)([a-zA-Z0-9_-]{11})", url)
    return m.group(1) if m else None


def fetch_all_entries(url):
    opts = {
        **_YTDL_COMMON,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    playlist_title = info.get("playlist_title") or info.get("title") or "playlist"
    entries = list(info.get("entries", []))

    videos = []
    for entry in entries:
        if not entry:
            continue
        title = entry.get("title") or entry.get("id") or "unknown"
        vid_id = entry.get("id") or ""
        ep_num = extract_episode_number(title)
        videos.append({
            "title": title,
            "id": vid_id,
            "episode": ep_num,
        })

    return playlist_title, videos


def fetch_sample_resolutions(videos, sample_count=5):
    opts = {
        **_YTDL_COMMON,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    seen = {}
    for vid in videos[:sample_count]:
        vid_url = f"https://www.youtube.com/watch?v={vid['id']}"
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                vinfo = ydl.extract_info(vid_url, download=False)
        except Exception:
            continue

        for f in (vinfo.get("formats") or []):
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
            if key not in seen:
                seen[key] = {
                    "height": height, "label": key,
                    "format_id": fmt_id, "filesize": filesize,
                    "has_audio": has_audio, "count": 0, "total_size": 0, "avg_size": 0,
                }

            cur = seen[key]
            if has_audio and not cur["has_audio"]:
                seen[key] = {**cur, "format_id": fmt_id, "filesize": filesize, "has_audio": True}
            elif has_audio == cur["has_audio"] and filesize > cur["filesize"]:
                seen[key] = {**cur, "format_id": fmt_id, "filesize": filesize}

    for r in seen.values():
        r["count"] += 1
        r["total_size"] += r["filesize"]

    return sorted(seen.values(), key=lambda x: -x["height"])


def resolve_start(videos, start_ep):
    matched = [v for v in videos if v["episode"] is not None and v["episode"] >= start_ep]
    matched.sort(key=lambda x: x["episode"])
    return matched


def find_by_link(videos):
    print()
    print("  Paste the exact video link to start from:")
    link = input("  Link: ").strip()
    if not link:
        return None, None

    target_id = extract_video_id(link)
    if not target_id:
        print("  [ERROR] Could not extract video ID from link.")
        return None, None

    for i, v in enumerate(videos):
        if v["id"] == target_id:
            return videos[i:], v["title"]

    print("  [ERROR] Video not found in this playlist.")
    return None, None


def main():
    clear_screen()
    print("== Custom Playlist Download ========================")
    print()
    print("  Download episodes from a playlist starting at")
    print("  a specific episode number or video link.")
    print()

    url = input("  Paste playlist URL: ").strip()
    if not url:
        print("  (cancelled)")
        return

    print()
    start_input = input("  Start from episode number: ").strip()

    print()
    print("  Fetching playlist...")

    try:
        playlist_title, videos = fetch_all_entries(url)
    except Exception as e:
        print(f"  [ERROR] Failed: {e}")
        input("  Press Enter to close...")
        return

    print(f"  Playlist: {playlist_title}")
    print(f"  Total videos: {len(videos)}")
    print()

    start_ep = None
    matched = []

    if start_input.isdigit():
        start_ep = int(start_input)
        matched = resolve_start(videos, start_ep)

        if matched:
            matched_with_ep = [v for v in videos if v["episode"] is not None]
            no_ep = [v for v in videos if v["episode"] is None]

            print(f"  Found: {len(matched)} episodes starting from ep {start_ep}")
            print(f"  (Episodes detected in {len(matched_with_ep)}/{len(videos)} videos)")
            if no_ep:
                print(f"  ({len(no_ep)} videos had no detectable episode number)")
        else:
            print(f"  Could not find episode {start_ep} in titles.")
            print()
            ans = input("  Paste a video link instead? (Y/n): ").strip().lower()
            if ans == "n":
                print("  (cancelled)")
                input("  Press Enter to close...")
                return
            matched, found_title = find_by_link(videos)
            if not matched:
                input("  Press Enter to close...")
                return
            print(f"  Starting from: {found_title}")
    else:
        print("  No episode number given.")
        matched, found_title = find_by_link(videos)
        if not matched:
            input("  Press Enter to close...")
            return
        print(f"  Starting from: {found_title}")

    if not matched:
        print("  [ERROR] No videos to download.")
        input("  Press Enter to close...")
        return

    print()
    print(f"  Will download {len(matched)} videos:")
    print()
    for v in matched:
        ep_label = f"Ep {v['episode']}" if v["episode"] else "    "
        print(f"    {ep_label:>6}  {v['title']}")
    print()

    print("  Select download folder...")
    root = tk.Tk()
    root.withdraw()
    folder = filedialog.askdirectory(title="Select download folder")
    root.destroy()
    if not folder:
        print("  (cancelled)")
        input("  Press Enter to close...")
        return

    print(f"  Folder: {folder}")
    print()
    print("  Fetching resolutions (sampling)...")

    resolutions = fetch_sample_resolutions(matched)

    if not resolutions:
        print("  [ERROR] No downloadable formats found.")
        input("  Press Enter to close...")
        return

    print()
    print(f"  {'ID':<5} {'Resolution':<12} {'Est. Total':<14} {'Avg/Video':<14}")
    print(f"  {'-'*5} {'-'*12} {'-'*14} {'-'*14}")

    for i, r in enumerate(resolutions, 1):
        avg = r["filesize"] if r["filesize"] > 0 else 0
        total_est = avg * len(matched)
        print(f"  {i:<5} {r['label']:<12} {format_size(total_est):<14} {format_size(avg):<14}")

    print()
    while True:
        choice = input(f"  Select resolution ID (1-{len(resolutions)}): ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(resolutions):
                chosen = resolutions[idx]
                break
        print(f"  [!] Enter a number between 1 and {len(resolutions)}")

    print()
    print(f"  Selected: {chosen['label']}")
    print(f"  Downloading {len(matched)} videos to: {folder}")
    print()

    success = 0
    fail = 0

    for i, vid in enumerate(matched, 1):
        vid_url = f"https://www.youtube.com/watch?v={vid['id']}"
        ep_label = f"Ep {vid['episode']}" if vid["episode"] else "    "
        print(f"  [{i}/{len(matched)}] {ep_label} - {vid['title']}")

        ok, _ = download_playlist_video(
            vid_url,
            folder,
            target_height=chosen["height"],
            format_id=chosen["format_id"],
        )

        if ok:
            success += 1
            print(f"  [{i}/{len(matched)}] Done")
        else:
            fail += 1
            print(f"  [{i}/{len(matched)}] Failed")
        print()

    print(f"  Finished: {success} downloaded, {fail} failed")
    print(f"  Output:   {folder}")
    input("  Press Enter to close...")


if __name__ == "__main__":
    main()
