import json
import subprocess
import sys
from pathlib import Path


def check_demucs_installed() -> bool:
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import demucs_onnx; print('ok')"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0 and "ok" in result.stdout
    except Exception:
        return False


def install_demucs() -> bool:
    print("  [VOCAL] Installing demucs-onnx...", flush=True)
    print("  [VOCAL] This downloads ~50MB of packages.", flush=True)
    print()

    result = subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "demucs-onnx[mp3]",
        ],
        capture_output=True, text=True, timeout=300,
    )

    if result.returncode != 0:
        print(f"  [VOCAL] Install failed: {result.stderr[:300]}", flush=True)
        return False

    return check_demucs_installed()


def ensure_model_downloaded() -> bool:
    if not check_demucs_installed():
        print("  [VOCAL] demucs-onnx not installed.", flush=True)
        return False

    print("  [VOCAL] Model will be auto-downloaded on first use (~316MB, one time).", flush=True)
    return True


def shutil_rmtree(path: Path):
    import shutil
    if path.exists() and path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def separate_vocals(input_path: str, output_dir: str) -> dict | None:
    input_p = Path(input_path)
    output_p = Path(output_dir)
    output_p.mkdir(parents=True, exist_ok=True)

    if not input_p.exists():
        print(f"  [VOCAL] File not found: {input_p}", flush=True)
        return None

    stem = input_p.stem
    clip_out = output_p / stem
    clip_out.mkdir(parents=True, exist_ok=True)

    AUDIO_EXTS = {".wav", ".mp3", ".flac", ".ogg", ".aac", ".wma", ".m4a"}
    audio_input = input_p
    temp_wav = None

    if input_p.suffix.lower() not in AUDIO_EXTS:
        temp_wav = output_p / f"{stem}_temp.wav"
        print(f"  [VOCAL] Extracting audio to WAV...", flush=True)
        result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(input_p),
                "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
                str(temp_wav),
            ],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            print(f"  [VOCAL] ffmpeg extract failed: {result.stderr[:200]}", flush=True)
            shutil_rmtree(clip_out)
            return None
        audio_input = temp_wav

    py_code = (
        "from demucs_onnx.cli import main; import sys; "
        f"sys.argv = ['demucs-onnx', 'separate', {json.dumps(str(audio_input))}, "
        f"{json.dumps(str(clip_out))}, "
        "'--stem', 'vocals', '--mp3']; main()"
    )
    cmd = [sys.executable, "-c", py_code]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)

    if result.returncode != 0:
        print(f"  [VOCAL] Failed: {result.stderr[:300]}", flush=True)
        return None

    vocals = None
    instrumental = None

    for p in clip_out.rglob("*.mp3"):
        name_lower = p.name.lower()
        if "vocal" in name_lower:
            vocals = p
        elif "no_vocal" in name_lower or "instrumental" in name_lower or "karaoke" in name_lower:
            instrumental = p

    if not vocals:
        mp3s = list(clip_out.rglob("*.mp3"))
        if len(mp3s) >= 2:
            mp3s.sort(key=lambda x: x.stat().st_size)
            instrumental = mp3s[0]
            vocals = mp3s[1]
        elif len(mp3s) == 1:
            vocals = mp3s[0]

    if vocals:
        final_vocals = output_p / f"{stem}_vocals.mp3"
        final_instrumental = output_p / f"{stem}_instrumental.mp3"
        if vocals != final_vocals:
            vocals.rename(final_vocals)
            vocals = final_vocals
        if instrumental and instrumental != final_instrumental:
            instrumental.rename(final_instrumental)
            instrumental = final_instrumental

    shutil_rmtree(clip_out)

    if temp_wav and temp_wav.exists():
        temp_wav.unlink(missing_ok=True)

    return {
        "vocals": str(vocals) if vocals else None,
        "instrumental": str(instrumental) if instrumental else None,
    }


def separate_vocals_batch(
    clip_paths: list[str],
    output_dir: str,
) -> list[dict]:
    results = []
    total = len(clip_paths)

    for i, clip_path in enumerate(clip_paths, 1):
        name = Path(clip_path).name
        print(f"  [VOCAL] [{i}/{total}] Separating: {name}", flush=True)

        result = separate_vocals(clip_path, output_dir)
        if result and result.get("vocals"):
            v_size = Path(result["vocals"]).stat().st_size / 1024 / 1024
            i_size = Path(result["instrumental"]).stat().st_size / 1024 / 1024 if result.get("instrumental") else 0
            print(f"  [VOCAL] [{i}/{total}] Done: vocals={v_size:.1f}MB, instrumental={i_size:.1f}MB", flush=True)
        else:
            print(f"  [VOCAL] [{i}/{total}] Failed", flush=True)

        results.append(result)

    return results


def create_vocals_video(video_path: str, vocals_mp3: str, output_path: str) -> bool:
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", vocals_mp3,
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            output_path,
        ],
        capture_output=True, text=True, timeout=120,
    )
    return result.returncode == 0
