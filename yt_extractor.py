import re
import unicodedata
from pathlib import Path

import yt_dlp
from downloader import sanitize_filename, _YTDL_COMMON
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, VideoUnavailable


def extract_video_id(url):
    m = re.search(r"(?:v=|/v/|youtu\.be/|embed/|shorts/)([a-zA-Z0-9_-]{11})", url)
    return m.group(1) if m else None


def get_video_title(url):
    try:
        opts = {**_YTDL_COMMON, "quiet": True, "skip_download": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return info.get("title", "")
    except Exception:
        return ""


def check_extracted(output_dir, title):
    extracted_file = Path(output_dir) / "extracted.txt"
    if not extracted_file.exists():
        return False
    try:
        with open(extracted_file, "r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r"\d+\.\s*(.*)", line.strip())
                if m and m.group(1) == title:
                    return True
    except Exception:
        pass
    return False


def append_extracted(output_dir, title):
    extracted_file = Path(output_dir) / "extracted.txt"
    lines = []
    try:
        with open(extracted_file, "r", encoding="utf-8") as f:
            for line in f:
                lines.append(line)
    except FileNotFoundError:
        pass
    lines.append(f"{title}\n")
    with open(extracted_file, "w", encoding="utf-8") as f:
        for i, line in enumerate(lines, 1):
            text = re.sub(r"^\d+\.\s*", "", line.rstrip("\n"))
            f.write(f"{i}. {text}\n")


def _fmt_ts(seconds):
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    s = int(seconds) % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def extract_transcript(url, output_dir, lang=None, include_timestamps=True):
    video_id = extract_video_id(url)
    if not video_id:
        print("  [TRANSCRIPT] Could not extract video ID", flush=True)
        return None

    title = get_video_title(url)
    safe_title = sanitize_filename(title) if title else video_id

    try:
        available = list(YouTubeTranscriptApi().list(video_id))
    except VideoUnavailable:
        print("  [TRANSCRIPT] Video is unavailable", flush=True)
        return None
    except Exception as e:
        print(f"  [TRANSCRIPT] Error: {e}", flush=True)
        return None

    if not available:
        print("  [TRANSCRIPT] No transcript available", flush=True)
        return None

    if lang:
        chosen_lang = lang
    else:
        chosen_lang = available[0].language_code

    try:
        transcript = YouTubeTranscriptApi().fetch(video_id, languages=[chosen_lang])
    except NoTranscriptFound:
        chosen_lang = available[0].language_code
        transcript = available[0].fetch()
    except Exception as e:
        print(f"  [TRANSCRIPT] Error: {e}", flush=True)
        return None

    out_dir = Path(output_dir) / safe_title
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{safe_title}_transcript.txt"

    count = 0
    with open(out_file, "w", encoding="utf-8") as f:
        for snippet in transcript.snippets:
            text = snippet.text.strip()
            if text:
                text = re.sub(r"\s+", " ", text)
                count += 1
                if include_timestamps:
                    f.write(f"[{_fmt_ts(snippet.start)}] {text}\n")
                else:
                    f.write(f"{text}\n")

    print(f"  [TRANSCRIPT] {count} lines -> {out_file.name}", flush=True)
    return str(out_file)


_EMOJI_PATTERN = re.compile(
    "[\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U0000FE00-\U0000FE0F"
    "\U0000200D"
    "\U00002300-\U000023FF"
    "\U000025A0-\U000025FF"
    "\U00002100-\U0000214F"
    "\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF"
    "\U000020D0-\U000020FF"
    "\U00003030-\U0000303F"
    "\U00003297-\U0000329F"
    "]+",
    re.UNICODE,
)


def _strip_emojis(text):
    return _EMOJI_PATTERN.sub("", text)


def _strip_mentions(text):
    return re.sub(r"@\S+\s*", "", text).strip()


def _normalize_key(text):
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201C", '"').replace("\u201D", '"')
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("\u00A0", " ").replace("\u200B", "").replace("\uFEFF", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text.lower()


def extract_comments(url, output_dir, max_comments=None):
    from yt_dlp.extractor.youtube import YoutubeIE

    video_id = extract_video_id(url)
    if not video_id:
        print("  [COMMENTS] Could not extract video ID", flush=True)
        return None

    title = get_video_title(url)
    safe_title = sanitize_filename(title) if title else video_id

    out_dir = Path(output_dir) / safe_title
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{safe_title}_comments.txt"

    counter = 0
    seen_texts = set()
    original_comment_entries = YoutubeIE._comment_entries

    def _patched_comment_entries(self, *args, **kwargs):
        nonlocal counter
        for comment in original_comment_entries(self, *args, **kwargs):
            if comment:
                text = comment.get("text", "")
                if text:
                    text = _strip_emojis(text)
                    text = _strip_mentions(text)
                    text = re.sub(r"\s+", " ", text).strip()
                    if text:
                        key = _normalize_key(text)
                        if key not in seen_texts:
                            seen_texts.add(key)
                            counter += 1
                            with open(out_file, "a", encoding="utf-8") as f:
                                f.write(f"{counter}. {text}\n")
            yield comment

    YoutubeIE._comment_entries = _patched_comment_entries

    try:
        out_file.write_text("", encoding="utf-8")

        opts = {
            **_YTDL_COMMON,
            "getcomments": True,
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
        }
        if max_comments:
            opts["extractor_args"] = {"youtube": {"max_comments": [str(max_comments)]}}

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=False)
    finally:
        YoutubeIE._comment_entries = original_comment_entries

    print(f"  [COMMENTS] {counter} comments -> {out_file.name}", flush=True)
    return str(out_file)


def extract_comment_count(url, output_dir):
    video_id = extract_video_id(url)
    if not video_id:
        print("  [COUNT] Could not extract video ID", flush=True)
        return None

    title = get_video_title(url)
    safe_title = sanitize_filename(title) if title else video_id

    opts = {**_YTDL_COMMON, "quiet": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    count = info.get("comment_count", None)
    display_title = info.get("title", safe_title)

    out_dir = Path(output_dir) / safe_title
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{safe_title}_comment-quantity.txt"

    if count is not None:
        line = f"{display_title} -- {count:,} comments"
    else:
        line = f"{display_title} -- Comment count: unknown"

    out_file.write_text(line + "\n", encoding="utf-8")
    print(f"  [COUNT] {line}", flush=True)
    return str(out_file)
