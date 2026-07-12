import argparse
import sys
from pathlib import Path

from clipper import clip_with_ffmpeg, parse_timecsv


def _separate_one_clip(clip_path: str, output_dir: str, clip_num: int):
    try:
        from vocal_remover import separate_vocals, create_vocals_video
    except ImportError:
        return

    vocal_dir = str(Path(output_dir) / "separated")
    result = separate_vocals(clip_path, vocal_dir)
    if result and result.get("vocals"):
        v_size = Path(result["vocals"]).stat().st_size / 1024 / 1024
        print(f"  [VOCAL] Vocals: {Path(result['vocals']).name} ({v_size:.1f}MB)", flush=True)

        vocals_only_path = str(Path(output_dir) / f"vocals_only_video_{clip_num}.mp4")
        if create_vocals_video(clip_path, result["vocals"], vocals_only_path):
            ov_size = Path(vocals_only_path).stat().st_size / 1024 / 1024
            print(f"  [VOCAL] Vocals-only video: vocals_only_video_{clip_num}.mp4 ({ov_size:.1f}MB)", flush=True)
        else:
            print(f"  [VOCAL] Failed to create vocals-only video", flush=True)
    else:
        print(f"  [VOCAL] Separation failed for {Path(clip_path).name}", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="Clip video into segments based on timestamps in time.csv"
    )
    parser.add_argument("video", nargs="?", default=None, help="Path to local video file")
    parser.add_argument("--url", default=None, help="YouTube video URL")
    parser.add_argument("--format", default=None, help="yt-dlp format ID for YouTube download")
    parser.add_argument("--no-audio", action="store_true", help="Format is video-only, pair with bestaudio")
    parser.add_argument("--height", type=int, default=0, help="Video height for format sorting")
    parser.add_argument("--csv", default="data/time.csv", help="Path to time.csv (default: data/time.csv)")
    parser.add_argument("-o", "--output", default="output", help="Output directory")
    parser.add_argument("--subfolder", default="default", help="Subfolder name inside output")
    parser.add_argument("--separate-vocals", action="store_true", help="Separate vocals after each clip")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"[ERROR] CSV file not found: {csv_path}")
        return

    if args.url:
        from downloader import download_clips_directly

        timestamps = parse_timecsv(str(csv_path))
        print(f"  Found {len(timestamps)} timestamp(s) in {csv_path}")
        for i, (start, end, label) in enumerate(timestamps, 1):
            print(f"    {i}. {start // 60}:{start % 60:02d} - {end // 60}:{end % 60:02d}")
        print()

        output_dir = str(Path(args.output) / "_clips")
        print(f"  Downloading only the {len(timestamps)} clips from YouTube...")
        print()

        clips, title = download_clips_directly(
            args.url,
            timestamps,
            output_dir,
            format_id=args.format,
            has_audio=not args.no_audio,
            height=args.height,
        )

        final_dir = str(Path(args.output) / title)
        Path(final_dir).mkdir(parents=True, exist_ok=True)

        import shutil
        for c in clips:
            dest = str(Path(final_dir) / Path(c).name)
            shutil.move(c, dest)

        if Path(output_dir).exists():
            shutil.rmtree(output_dir, ignore_errors=True)

        print()
        sorted_clips = sorted(Path(final_dir).iterdir(), key=lambda p: p.name)
        clip_num = 1
        for c in sorted_clips:
            if c.suffix == ".mp4":
                size = c.stat().st_size / 1024 / 1024
                print(f"  {c.name}  ({size:.1f} MB)")
                if args.separate_vocals:
                    _separate_one_clip(str(c), final_dir, clip_num)
                    clip_num += 1

        print(f"\nDone! {len(clips)} clip(s) saved to output/{title}/")

    elif args.video:
        video_path = Path(args.video).resolve()
        if not video_path.exists():
            print(f"[ERROR] Video file not found: {video_path}")
            return

        output_dir = str(Path(args.output) / args.subfolder)
        print(f"  Video:  {video_path}")
        print(f"  CSV:    {csv_path}")
        print(f"  Output: {output_dir}")
        print()

        timestamps = parse_timecsv(str(csv_path))
        print(f"  Found {len(timestamps)} timestamp(s)")
        for i, (start, end, label) in enumerate(timestamps, 1):
            print(f"    {i}. {start // 60}:{start % 60:02d} - {end // 60}:{end % 60:02d}")
        print()

        print("  Clipping (ffmpeg -c copy, instant)...")
        clips = clip_with_ffmpeg(str(video_path), timestamps, output_dir)

        print()
        for i, c in enumerate(clips, 1):
            size = Path(c).stat().st_size / 1024 / 1024
            print(f"  {Path(c).name}  ({size:.1f} MB)")
            if args.separate_vocals:
                _separate_one_clip(c, output_dir, i)

        print(f"\nDone! {len(clips)} clip(s) created.")

    else:
        print("[ERROR] Provide a video path or --url <youtube_url>")
        return


if __name__ == "__main__":
    main()
