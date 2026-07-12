"""
Silence Remover — remove silent regions from audio files
"""

import os
import tkinter as tk
from tkinter import filedialog
from pydub import AudioSegment
from pydub.silence import split_on_silence, detect_silence

# ── Settings ─────────────────────────────────────
MIN_SILENCE_LEN = 200   # ms — minimum silence to remove
SILENCE_THRESH = -40    # dBFS — silence threshold
KEEP_SILENCE = 50       # ms — padding on retained segments
OUTPUT_FORMAT = "wav"   # lossless
# ─────────────────────────────────────────────────


def fmt_time(ms):
    s = ms // 1000
    h, m, s = s // 3600, (s % 3600) // 60, s % 60
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def main():
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    path = filedialog.askopenfilename(
        title="Select audio file",
        filetypes=[("Audio files", "*.wav *.mp3 *.m4a *.flac *.ogg *.aac"),
                   ("All files", "*.*")]
    )
    if not path:
        print("No file selected.")
        return

    print(f"\nLoading: {path}")
    try:
        audio = AudioSegment.from_file(path)
    except Exception as e:
        print(f"Error: Could not load file.\n{e}\n\nMake sure ffmpeg is installed for non-WAV files.")
        return

    orig_ms = len(audio)
    print("Analyzing silence...")

    silent = detect_silence(audio,
                            min_silence_len=MIN_SILENCE_LEN,
                            silence_thresh=SILENCE_THRESH)
    num_silent = len(silent)

    parts = split_on_silence(audio,
                             min_silence_len=MIN_SILENCE_LEN,
                             silence_thresh=SILENCE_THRESH,
                             keep_silence=KEEP_SILENCE)

    if not parts:
        print("No non-silent segments found. Try lowering SILENCE_THRESH.")
        return

    result = sum(parts)
    out_ms = len(result)
    saved_ms = orig_ms - out_ms

    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    out_path = os.path.join(out_dir, f"{stem}_nosilence.{OUTPUT_FORMAT}")

    print("Exporting...")
    result.export(out_path, format=OUTPUT_FORMAT)

    print()
    print("=" * 52)
    print("  Silence Remover — Done")
    print("=" * 52)
    print(f"  Input:    {os.path.basename(path)}")
    print(f"  Duration: {fmt_time(orig_ms)}")
    print(f"  Output:   output\\{os.path.basename(out_path)}")
    print(f"  Duration: {fmt_time(out_ms)}")
    print(f"  Removed:  {fmt_time(saved_ms)} ({num_silent} silent segment{'s' if num_silent != 1 else ''})")
    print("=" * 52)


if __name__ == "__main__":
    main()
    input("\nPress Enter to exit...")
