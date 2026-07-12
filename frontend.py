import os
import re
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

BASE = Path(__file__).parent
QUEUE_FILE = BASE / "queue.txt"


def load_queue():
    if not QUEUE_FILE.exists():
        return []
    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def save_queue(queue):
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        for item in queue:
            f.write(item + "\n")


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def is_youtube_url(s):
    return re.match(r"^https?://(www\.)?(youtube\.com|youtu\.be)/", s) is not None


def pick_file():
    root = tk.Tk()
    root.withdraw()
    path = filedialog.askopenfilename(
        title="Select video file",
        filetypes=[
            ("Video files", "*.mp4 *.avi *.mov *.mkv *.webm"),
            ("All files", "*.*"),
        ],
    )
    root.destroy()
    return path


def menu():
    clear_screen()
    queue = load_queue()
    csv_path = BASE / "time.csv"
    csv_exists = csv_path.exists()

    print("=" * 50)
    print("  Timestamp Video Clipper")
    print("=" * 50)
    print()
    print("  Clips video using timestamps from time.csv")
    print("  Output: original size, no cropping or scaling")
    print()
    if csv_exists:
        print(f"  time.csv: OK")
    else:
        print(f"  time.csv: NOT FOUND (place it in project folder)")
    print()
    print(f"  --- Local Files ---")
    print(f"  [1]  Add Video File")
    print(f"  [2]  List Queue  ({len(queue)} queued)")
    print(f"  [3]  Remove from Queue")
    print(f"  [4]  Clear Queue")
    print()
    print(f"  [5]  Process All  ({len(queue)} video(s))")
    print(f"  [6]  Process One")
    print()
    print(f"  --- YouTube ---")
    print(f"  [8]  YouTube Direct")
    print()
    print(f"  --- Setup ---")
    print(f"  [9]  Check / Install Requirements")
    print()
    print(f"  [7]  Exit")
    print()
    return input("Select: ").strip()


def add_file():
    clear_screen()
    print("-- Add Video File -----------------------------------")
    print()
    print("Opening file browser...")
    path = pick_file()
    if not path:
        print("(cancelled)")
        input("Press Enter to continue...")
        return
    queue = load_queue()
    queue.append(path)
    save_queue(queue)
    print()
    print(f"[OK] Added: {path}")
    input("Press Enter to continue...")


def list_queue():
    clear_screen()
    print("-- Queue --------------------------------------------")
    print()
    queue = load_queue()
    if not queue:
        print("  (empty queue)")
    else:
        for i, item in enumerate(queue, 1):
            display = item if len(item) < 78 else item[:75] + "..."
            print(f"  {i:>2}. {display}")
    print()
    print(f"  Total: {len(queue)} item(s)")
    print()
    input("Press Enter to continue...")


def remove_file():
    clear_screen()
    queue = load_queue()
    if not queue:
        print("Queue is empty.")
        input("Press Enter to continue...")
        return
    print("-- Remove from Queue --------------------------------")
    print()
    for i, item in enumerate(queue, 1):
        print(f"  {i:>2}. {item}")
    print()
    rn = input("Enter number to remove (or 0 to cancel): ").strip()
    if not rn or rn == "0":
        return
    try:
        idx = int(rn) - 1
        if idx < 0 or idx >= len(queue):
            raise ValueError
        removed = queue.pop(idx)
        save_queue(queue)
        print()
        print(f"[OK] Removed: {removed}")
    except ValueError:
        print("[ERROR] Invalid number.")
    input("Press Enter to continue...")


def clear_queue():
    clear_screen()
    print("-- Clear Queue --------------------------------------")
    print()
    confirm = input("Clear all items from queue? (y/n): ").strip().lower()
    if confirm == "y":
        save_queue([])
        print("[OK] Queue cleared.")
    input("Press Enter to continue...")


def build_cmd(video_path, subfolder="default", separate_vocals=False):
    cmd = [sys.executable or "python", "-u", str(BASE / "main.py")]
    cmd.append(str(video_path))
    cmd.extend(["--csv", str(BASE / "time.csv")])
    cmd.extend(["-o", str(BASE / "output")])
    cmd.extend(["--subfolder", subfolder])
    if separate_vocals:
        cmd.append("--separate-vocals")
    return cmd


def process_item(item, idx, total, subfolder="default", separate_vocals=False):
    clear_screen()
    short = item if len(item) < 78 else item[:75] + "..."
    print(f"  [{idx}/{total}]  {short}")
    print(f"  Subfolder: {subfolder}")
    print(f"  {'─' * 60}")
    print()

    cmd = build_cmd(item, subfolder=subfolder, separate_vocals=separate_vocals)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    result = subprocess.run(cmd, timeout=1800, env=env)
    if result.returncode == 0:
        print(f"  [OK] Item {idx} complete.")
    else:
        print(f"  [!!] Item {idx} failed (exit code {result.returncode}).")
    return result.returncode


def process_all():
    queue = load_queue()
    if not queue:
        print("Queue is empty. Add items first.")
        input("Press Enter to continue...")
        return
    clear_screen()
    print(f"  Processing {len(queue)} item(s)")
    print(f"  {'─' * 40}")
    print()

    csv_path = BASE / "time.csv"
    if not csv_path.exists():
        print(f"  [ERROR] time.csv not found at {csv_path}")
        input("Press Enter to continue...")
        return

    from vocal_remover import check_demucs_installed, ensure_model_downloaded, install_demucs
    separate_vocals = False
    answer = input("  Separate vocals from clips? (y/n): ").strip().lower()
    if answer == "y":
        if not check_demucs_installed():
            if not install_demucs():
                print("  [VOCAL] Install failed. Continuing without vocal separation.")
            else:
                print("  [VOCAL] Installed successfully.")
        if check_demucs_installed():
            if not ensure_model_downloaded():
                print("  [VOCAL] Could not verify model. Continuing without vocal separation.")
            else:
                separate_vocals = True

    print()
    print(f"  Using timestamps from: {csv_path}")
    print()
    subfolder = input("  Output subfolder (Enter=default): ").strip() or "default"
    print()
    for i, item in enumerate(queue, 1):
        rc = process_item(item, i, len(queue), subfolder=subfolder, separate_vocals=separate_vocals)
        if i < len(queue):
            print("\n  Next item in 3 seconds...")
            time.sleep(3)
    print()
    print("  [DONE] All items processed.")
    input("Press Enter to continue...")


def process_one():
    queue = load_queue()
    if not queue:
        print("Queue is empty. Add items first.")
        input("Press Enter to continue...")
        return
    clear_screen()
    print("-- Select Item to Process ---------------------------")
    print()

    from vocal_remover import check_demucs_installed, ensure_model_downloaded, install_demucs
    separate_vocals = False
    answer = input("  Separate vocals from clips? (y/n): ").strip().lower()
    if answer == "y":
        if not check_demucs_installed():
            if not install_demucs():
                print("  [VOCAL] Install failed. Continuing without vocal separation.")
            else:
                print("  [VOCAL] Installed successfully.")
        if check_demucs_installed():
            if not ensure_model_downloaded():
                print("  [VOCAL] Could not verify model. Continuing without vocal separation.")
            else:
                separate_vocals = True

    print()
    for i, item in enumerate(queue, 1):
        print(f"  {i:>2}. {item}")
    print()
    pn = input("Enter number (or 0 to cancel): ").strip()
    if not pn or pn == "0":
        return
    try:
        idx = int(pn) - 1
        if idx < 0 or idx >= len(queue):
            raise ValueError
    except ValueError:
        print("[ERROR] Invalid number.")
        input("Press Enter to continue...")
        return
    print()
    subfolder = input("  Enter output subfolder name: ").strip() or "default"
    process_item(queue[idx], 1, 1, subfolder=subfolder, separate_vocals=separate_vocals)
    print()
    input("Press Enter to continue...")


def youtube_direct():
    clear_screen()
    print("-- YouTube Direct -----------------------------------")
    print()

    csv_path = BASE / "time.csv"
    if not csv_path.exists():
        print(f"  [ERROR] time.csv not found at {csv_path}")
        input("  Press Enter to continue...")
        return

    from vocal_remover import check_demucs_installed, ensure_model_downloaded, install_demucs
    separate_vocals = False
    answer = input("  Separate vocals from clips? (y/n): ").strip().lower()
    if answer == "y":
        if not check_demucs_installed():
            if not install_demucs():
                print("  [VOCAL] Install failed. Continuing without vocal separation.")
            else:
                print("  [VOCAL] Installed successfully.")
        if check_demucs_installed():
            if not ensure_model_downloaded():
                print("  [VOCAL] Could not verify model. Continuing without vocal separation.")
            else:
                separate_vocals = True

    print()
    url = input("  Paste YouTube URL: ").strip()
    if not url:
        print("  (cancelled)")
        input("  Press Enter to continue...")
        return
    if not is_youtube_url(url):
        print("  [ERROR] Not a valid YouTube URL.")
        input("  Press Enter to continue...")
        return

    from clipper import parse_timecsv
    try:
        timestamps = parse_timecsv(str(csv_path))
    except Exception as e:
        print(f"  [ERROR] {e}")
        input("  Press Enter to continue...")
        return

    total_clip_secs = sum(end - start for start, end, _ in timestamps)
    total_clip_min = total_clip_secs // 60
    total_clip_sec = total_clip_secs % 60
    print(f"  Segments from time.csv ({len(timestamps)} clips, ~{total_clip_min}m{total_clip_sec:02d}s total):")
    for i, (start, end, label) in enumerate(timestamps, 1):
        dur = end - start
        print(f"    {i}. {start // 60}:{start % 60:02d} - {end // 60}:{end % 60:02d}  ({dur // 60}m{dur % 60:02d}s)")
    print()

    print("  Fetching video info...")
    try:
        from downloader import (
            check_cached_source,
            estimate_clip_sizes,
            fetch_formats,
            format_size,
            get_video_info,
            sanitize_filename,
        )
        formats, title, total_duration = fetch_formats(url)
        dur_min = total_duration // 60
        dur_sec = total_duration % 60
    except Exception as e:
        print(f"  [ERROR] Failed to fetch: {e}")
        input("  Press Enter to continue...")
        return

    if not formats:
        print("  No suitable video formats found.")
        input("  Press Enter to continue...")
        return

    temp_dir = str(BASE / "output" / "_temp")
    cached = check_cached_source(temp_dir)
    audio_map = {}
    if cached:
        print(f"  Cached: {cached.name} ({cached.stat().st_size / 1024 / 1024:.0f}MB) — skipping download")
    else:
        print(f"  Title:    {title}")
        print(f"  Duration: {dur_min}:{dur_sec:02d}")
        print()

        clips_total_dur = sum(end - start for start, end, _ in timestamps)
        print(f"  {'ID':>6}  {'EXT':>4}  {'RESOLUTION':>12}  {'AUDIO':>6}  {'METHOD':>16}  {'ORIGINAL':>10}  {'CLIPS (~)':>16}")
        print(f"  {'─'*6}  {'─'*4}  {'─'*12}  {'─'*6}  {'─'*16}  {'─'*10}  {'─'*16}")
        audio_map = {}
        for f in formats:
            dl_size = format_size(f["filesize"])
            if total_duration > 0 and f["filesize"] > 0:
                clips_bytes = int((clips_total_dur / total_duration) * f["filesize"])
            else:
                clips_bytes = 0
            if f["has_audio"]:
                audio_flag = "yes"
                method = "segments"
            else:
                audio_flag = "no"
                method = "segment/range/fallback"
                clips_bytes = int(clips_bytes * 1.5)
            clips_str = format_size(clips_bytes)
            audio_map[f["id"]] = {"has_audio": f["has_audio"], "height": f["height"]}
            print(f"  {f['id']:>6}  {f['ext']:>4}  {f['resolution']:>12}  {audio_flag:>6}  {method:>16}  {dl_size:>10}  {clips_str:>7} ({len(timestamps)} clips)")
        print()
        print(f"  yes = has audio built-in   no = video-only (audio merged separately)")
        print()
        print(f"  segments         = downloads only clip portions (fast, ~5s each)")
        print(f"  segment/range    = tries segment-aware, then range-estimation,")
        print(f"                     then full download (auto-fallback)")
        print(f"  ORIGINAL         = full video size   CLIPS = estimated clip total")
        print()

    fmt_input = input("  Select format ID (Enter=best): ").strip()
    fmt_id = fmt_input if fmt_input else None
    fmt_info = audio_map.get(fmt_id) if fmt_id else None
    fmt_has_audio = fmt_info["has_audio"] if fmt_info else True
    fmt_height = fmt_info["height"] if fmt_info else 0

    print()
    if cached:
        print(f"  Using cached source, clipping {len(timestamps)} segments...")
    else:
        print(f"  Downloading {len(timestamps)} clips...")
    print()

    cmd = [
        sys.executable or "python", "-u",
        str(BASE / "main.py"),
        "--url", url,
        "--csv", str(csv_path),
        "-o", str(BASE / "output"),
    ]
    if separate_vocals:
        cmd.append("--separate-vocals")
    if fmt_id:
        cmd.extend(["--format", fmt_id])
        cmd.extend(["--height", str(fmt_height)])
        if not fmt_has_audio:
            cmd.extend(["--no-audio"])

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    result = subprocess.run(cmd, timeout=1800, env=env)
    print()
    if result.returncode == 0:
        print("  [OK] YouTube clips created.")
    else:
        print(f"  [!!] Failed (exit code {result.returncode}).")
    input("  Press Enter to continue...")


def check_requirements():
    clear_screen()
    print("-- Check / Install Requirements --------------------")
    print()

    req_file = BASE / "requirements.txt"
    if not req_file.exists():
        print("  [!!] requirements.txt not found.")
        input("  Press Enter to continue...")
        return

    with open(req_file, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip() and not l.startswith("#")]

    print(f"  Found {len(lines)} packages in requirements.txt")
    print()

    missing = []
    installed = []

    for pkg in lines:
        pkg_name = re.split(r"[>=<!\[]", pkg)[0].strip()
        try:
            __import__(pkg_name.replace("-", "_"))
            installed.append(pkg)
        except ImportError:
            missing.append(pkg)

    if installed:
        print("  [OK] Installed:")
        for p in installed:
            print(f"        {p}")

    if missing:
        print()
        print("  [!!] Missing:")
        for p in missing:
            print(f"        {p}")
        print()
        ans = input("  Install missing packages? (y/n): ").strip().lower()
        if ans == "y":
            print()
            for pkg in missing:
                print(f"  Installing {pkg}...")
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", pkg],
                    capture_output=True, text=True, timeout=300,
                )
                if result.returncode == 0:
                    print(f"  [OK] {pkg}")
                else:
                    print(f"  [!!] Failed: {result.stderr[:200]}")
    else:
        print()
        print("  All requirements are satisfied!")

    print()
    input("  Press Enter to continue...")


def main():
    while True:
        choice = menu()
        if choice == "1":
            add_file()
        elif choice == "2":
            list_queue()
        elif choice == "3":
            remove_file()
        elif choice == "4":
            clear_queue()
        elif choice == "5":
            process_all()
        elif choice == "6":
            process_one()
        elif choice == "8":
            youtube_direct()
        elif choice == "9":
            check_requirements()
        elif choice == "7":
            break
        elif choice == "":
            pass
        else:
            clear_screen()
            print("  Invalid option. Enter a number 1-9.")
            input("  Press Enter to continue...")


if __name__ == "__main__":
    main()
