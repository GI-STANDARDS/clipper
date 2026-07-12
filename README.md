# Timestamp Video Clipper

A command-line tool for clipping videos into segments using timestamps from a CSV file. Supports local video files and YouTube URLs with smart segment-aware downloading.

## Features

### Core Clipping
- **Timestamp-based clipping** — reads `data/time.csv` and splits video into segments at original resolution (no cropping or scaling)
- **Batch processing** — queue multiple videos and process them all at once
- **Queue management** — add, list, remove, and clear videos from the processing queue

### YouTube Support
- **YouTube Direct** — paste a YouTube URL, pick a format, and download only the segments you need
- **3-layer fallback download** — segment-aware sidx parsing → range estimation → full download + clip
- **Format selection** — choose from available formats with size estimates for both full video and clips

### YouTube Extraction
- **Transcript extraction** — pull subtitles/transcripts from any YouTube video
- **Comments extraction** — download video comments (with optional max count)
- **Comment count** — get total comment count for a video
- **Duplicate detection** — tracks previously extracted videos in `output/extracted.txt`

### Audio & Vocals
- **Vocal separation** — uses demucs-onnx to separate vocals from audio tracks (per-clip or full bag)
- **Vocals-only video** — mux isolated vocals back into the video as a separate output
- **Silence remover** — remove silent regions from audio files with configurable thresholds

### Captioning
- **Audio captioner** — transcribe speech with Whisper, translate to any language, and render captions on video
- **Multiple Whisper models** — tiny, base, small, medium, large
- **Google Translate integration** — auto-translate transcribed text to target language

## Setup

### Prerequisites
- Python 3.10+ (3.11 recommended)
- FFmpeg (required for all video/audio operations)
- Node.js (required for yt-dlp YouTube downloads)

### Installation

1. Clone or download this project
2. Run `App.bat` — it will create the virtual environment and install dependencies automatically
3. Or manually:
   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

### Requirements
```
demucs-onnx[mp3]
moviepy
requests
tqdm
yt-dlp
youtube-transcript-api
openai-whisper
deep-translator
pydub
```

## Usage

Run `App.bat` or:
```
venv\Scripts\activate
python frontend.py
```

### Menu Options

| Key | Option | Description |
|-----|--------|-------------|
| `1` | Add Video File | Browse and add a local video to the queue |
| `2` | List Queue | Show all queued videos |
| `3` | Remove from Queue | Remove a specific video from the queue |
| `4` | Clear Queue | Remove all videos from the queue |
| `5` | Process All | Process all queued videos with timestamps |
| `6` | Process One | Process a single video from the queue |
| `7` | Exit | Exit the application |
| `8` | YouTube Direct | Download and clip from a YouTube URL |
| `9` | Check / Install Requirements | Verify and install missing packages |
| `10` | YouTube Extract | Extract transcript, comments, and comment count |
| `11` | Audio Captioner | Transcribe and caption a local video |
| `12` | Silence Remover | Remove silence from audio files |

### Creating timestamps

Create `data/time.csv` with one timestamp pair per line:
```
02:20 – 02:34
06:51 – 07:46
08:34 – 08:46
```

Format: `MM:SS – MM:SS` or `HH:MM:SS – HH:MM:SS`. Line numbers and en-dashes are supported.

### YouTube Direct workflow
1. Select `[8] YouTube Direct`
2. Paste the YouTube URL
3. View available formats with size estimates (full video vs clips only)
4. Pick a format ID or press Enter for best quality
5. Segments are downloaded and clipped to `output/`

### Vocal Separation
When processing videos (options 5, 6, or 8), you'll be asked if you want to separate vocals. If enabled:
- Each clip gets vocals isolated via demucs-onnx
- A `vocals_only_video_N.mp4` is created for each clip
- Uses `--stem vocals` for faster processing (vocals specialist only)

## Project Structure

```
timestamp clips/
├── App.bat                 # Launcher
├── frontend.py             # Main TUI menu
├── main.py                 # CLI entry point for clipping
├── clipper.py              # Video clipping + CSV parser
├── downloader.py           # YouTube download (3-layer fallback)
├── vocal_remover.py        # Demucs-onnx vocal separation
├── extractor.py            # YouTube transcript/comments extraction
├── captioner.py            # Whisper transcription + translation + captions
├── silence_remover.py      # Audio silence removal
├── config.py               # Default configuration
├── requirements.txt        # Python dependencies
├── data/
│   ├── time.csv            # Timestamps for clipping
│   ├── urls.txt            # YouTube URLs
│   └── queue.txt           # Video processing queue
└── output/                 # Generated clips and files
    ├── extracted.txt       # Log of extracted YouTube videos
    └── <video-title>/      # Per-video output folders
```

## CLI Usage

You can also run the clipper directly:
```
# Local video
python main.py video.mp4 --csv data/time.csv -o output

# YouTube URL
python main.py --url https://youtube.com/watch?v=... --csv data/time.csv -o output

# With vocal separation
python main.py video.mp4 --csv data/time.csv -o output --separate-vocals
```

## Notes
- Output clips are saved at original resolution with no quality loss
- YouTube segment downloading uses ffmpeg sub-processes for fast extraction
- The tool caches downloaded YouTube source files in `output/_temp/` to avoid re-downloading
- Whisper model files are downloaded on first use and cached locally
