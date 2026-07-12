import os
import subprocess
import sys
import tempfile
from pathlib import Path

import whisper
from deep_translator import GoogleTranslator
from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeVideoClip,
    TextClip,
)

from downloader import sanitize_filename


def extract_audio(video_path, audio_path):
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            str(audio_path),
        ],
        capture_output=True, text=True, timeout=300,
    )
    return result.returncode == 0


def transcribe_audio(audio_path, model_size="base"):
    print(f"  Loading Whisper model ({model_size})...", flush=True)
    model = whisper.load_model(model_size)

    print("  Transcribing audio...", flush=True)
    result = model.transcribe(audio_path, verbose=False)

    lang = result.get("language", "unknown")
    print(f"  Detected language: {lang}", flush=True)

    segments = []
    for seg in result["segments"]:
        segments.append(
            {
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"].strip(),
            }
        )

    print(f"  Transcribed {len(segments)} segments.", flush=True)
    return segments, lang


def translate_segments(segments, source_lang):
    lang_map = {"ar": "ar", "ja": "ja", "hi": "hi", "ur": "ur"}
    if source_lang not in lang_map:
        source_lang = "auto"

    print(f"  Translating {len(segments)} segments to English...", flush=True)

    translated = []
    for i, seg in enumerate(segments):
        try:
            result = GoogleTranslator(source=source_lang, target="en").translate(seg["text"])
            translated.append(
                {
                    "start": seg["start"],
                    "end": seg["end"],
                    "original": seg["text"],
                    "english": result if result else seg["text"],
                }
            )
            if (i + 1) % 20 == 0:
                print(f"  [{i+1}/{len(segments)}]", flush=True)
        except Exception as e:
            print(f"  [{i+1}/{len(segments)}] Failed, using original: {e}", flush=True)
            translated.append(
                {
                    "start": seg["start"],
                    "end": seg["end"],
                    "original": seg["text"],
                    "english": seg["text"],
                }
            )

    print(f"  [{len(segments)}/{len(segments)}] Done", flush=True)
    return translated


def find_font():
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibrib.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/times.ttf",
        "Arial-Bold",
        "Arial-BoldMT",
    ]
    for font in candidates:
        if os.path.isfile(font):
            return font
    return None


def generate_video(audio_path, translated_segments, output_path):
    print("  Loading audio...", flush=True)
    audio = AudioFileClip(audio_path)
    duration = audio.duration
    print(f"  Audio duration: {duration:.1f}s", flush=True)

    width, height = 1920, 1080
    bg_color = (255, 255, 255)

    print("  Creating background...", flush=True)
    video = ColorClip(size=(width, height), color=bg_color, duration=duration)

    font_path = find_font()
    font_size = 58
    font_name = "Arial-Bold"

    if font_path and os.path.isfile(font_path):
        font_name = font_path

    print("  Adding captions...", flush=True)
    text_clips = []
    for seg in translated_segments:
        text = seg["english"]
        if not text:
            continue

        start = seg["start"]
        end = seg["end"]

        if end > duration:
            end = duration
        if start >= end:
            continue

        txt_clip = (
            TextClip(
                text=text,
                font_size=font_size,
                color="black",
                font=font_name,
                method="caption",
                size=(width - 200, None),
                text_align="center",
            )
            .with_position(("center", height - 180))
            .with_start(start)
            .with_end(end)
        )
        text_clips.append(txt_clip)

    print(f"  Compositing {len(text_clips)} caption clips...", flush=True)
    final = CompositeVideoClip([video] + text_clips)
    final = final.with_audio(audio)

    print(f"  Rendering video...", flush=True)
    final.write_videofile(
        output_path,
        fps=24,
        codec="libx264",
        audio_codec="aac",
        threads=4,
        logger=None,
    )

    audio.close()
    final.close()
    print(f"  Video saved: {output_path}", flush=True)


def caption_video(input_path, output_dir, model_size="base"):
    input_p = Path(input_path)
    if not input_p.exists():
        print(f"  [CAPTION] File not found: {input_p}", flush=True)
        return None

    stem = input_p.stem
    title = sanitize_filename(stem)

    with tempfile.TemporaryDirectory() as tmp:
        audio_path = os.path.join(tmp, "audio.wav")

        print(f"  [CAPTION] Extracting audio from video...", flush=True)
        if not extract_audio(str(input_p), audio_path):
            print("  [CAPTION] Failed to extract audio", flush=True)
            return None
        print(f"  [CAPTION] Audio extracted.", flush=True)

        segments, lang = transcribe_audio(audio_path, model_size=model_size)
        if not segments:
            print("  [CAPTION] No segments transcribed", flush=True)
            return None

        translated = translate_segments(segments, lang)

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(out_dir / f"{title}_{lang}.mp4")

        generate_video(audio_path, translated, output_path)

    size_mb = Path(output_path).stat().st_size / 1024 / 1024
    print(f"  [CAPTION] Done: {Path(output_path).name} ({size_mb:.1f}MB)", flush=True)
    return output_path
