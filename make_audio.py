"""Turn Sefaria English Midrash chapters into MP3 episodes with Kokoro (free, local).

    .venv/Scripts/python make_audio.py --chapters 1
    .venv/Scripts/python make_audio.py --chapters 1-100

Resumable: a chapter whose MP3 already exists is skipped. Chapter text is
cached under data/text/ so each chapter is fetched from Sefaria once, ever.
"""
import argparse
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent
TEXT_DIR = ROOT / "data" / "text"
AUDIO_DIR = ROOT / "data" / "audio"
API = "https://www.sefaria.org/api/v3/texts/"

# Version titles come from /api/texts/versions/<book> (saved in _fixtures/sefaria).
BOOKS = {
    "Bereshit Rabbah": {"version": "The Sefaria Midrash Rabbah, 2022", "slug": "bereshit-rabbah"},
}
SAMPLE_RATE = 24000


def fetch_chapter(book: str, chapter: int) -> list[str]:
    """Return the chapter's English segments, from cache or one Sefaria request."""
    slug = BOOKS[book]["slug"]
    cache = TEXT_DIR / slug / f"{chapter:03d}.json"
    if not cache.exists():
        version = BOOKS[book]["version"]
        tref = urllib.parse.quote(f"{book} {chapter}")
        query = urllib.parse.urlencode({"version": f"english|{version}", "return_format": "text_only"})
        req = urllib.request.Request(f"{API}{tref}?{query}", headers={"User-Agent": "midrash-reader (personal listening)"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
        versions = data.get("versions") or []
        if len(versions) != 1 or versions[0].get("versionTitle") != version:
            raise RuntimeError(f"{book} {chapter}: expected version {version!r}, got {[v.get('versionTitle') for v in versions]} warnings={data.get('warnings')}")
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        time.sleep(2)  # gentle on Sefaria between chapters
    data = json.loads(cache.read_text(encoding="utf-8"))
    return [s for s in flatten(data["versions"][0]["text"]) if s and s.strip()]


def flatten(x):
    if isinstance(x, list):
        for item in x:
            yield from flatten(item)
    else:
        yield x


CITATION = re.compile(r"\b([1-3]?\s?[A-Z][A-Za-z']+(?: [A-Z][A-Za-z']+)*)\s(\d+):(\d+)(?:[–-](\d+))?")


def speakable(text: str) -> str:
    """Make written conventions sound right aloud; never changes the words themselves."""
    def cite(m):
        book, ch, v1, v2 = m.groups()
        verses = f"verses {v1} to {v2}" if v2 else f"verse {v1}"
        return f"{book}, chapter {ch}, {verses}"
    text = CITATION.sub(cite, text)
    text = text.replace("Ḥ", "Ch").replace("ḥ", "ch")   # transliterated het, said as in "Chanukah"
    text = text.replace("[", "").replace("]", "")   # editor's insertions are read as part of the sentence
    text = re.sub(r"\s+", " ", text).strip()
    return text


def synthesize(pipeline, voice: str, paragraphs: list[str]) -> np.ndarray:
    pause = np.zeros(int(SAMPLE_RATE * 0.9), dtype=np.float32)
    pieces = []
    for i, para in enumerate(paragraphs, 1):
        for _, _, audio in pipeline(para, voice=voice, speed=0.95, split_pattern=r"\n+"):
            pieces.append(np.asarray(audio, dtype=np.float32))
        pieces.append(pause)
        print(f"    paragraph {i}/{len(paragraphs)}", flush=True)
    return np.concatenate(pieces)


def write_mp3(audio: np.ndarray, out: Path, book: str, chapter: int) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "-",
           "-codec:a", "libmp3lame", "-b:a", "64k",
           "-metadata", f"title={book} {chapter}", "-metadata", f"album={book}",
           "-metadata", "artist=Sefaria English translation", "-metadata", f"track={chapter}",
           str(out)]
    subprocess.run(cmd, input=pcm, check=True)


def parse_range(s: str) -> list[int]:
    out = []
    for part in s.split(","):
        a, _, b = part.partition("-")
        out.extend(range(int(a), int(b or a) + 1))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="Bereshit Rabbah", choices=sorted(BOOKS))
    ap.add_argument("--chapters", required=True, help="e.g. 1 or 1-100 or 1,5,7-9")
    ap.add_argument("--voice", default="af_heart")
    args = ap.parse_args()

    from kokoro import KPipeline
    pipeline = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M")
    slug = BOOKS[args.book]["slug"]

    for ch in parse_range(args.chapters):
        out = AUDIO_DIR / slug / f"{slug}-{ch:03d}.mp3"
        if out.exists():
            print(f"{args.book} {ch}: already made, skipping")
            continue
        t0 = time.time()
        segments = fetch_chapter(args.book, ch)
        paragraphs = [f"{args.book}, chapter {ch}."] + [speakable(s) for s in segments]
        print(f"{args.book} {ch}: {len(segments)} paragraphs, {sum(map(len, segments)):,} characters", flush=True)
        audio = synthesize(pipeline, args.voice, paragraphs)
        write_mp3(audio, out, args.book, ch)
        print(f"{args.book} {ch}: {len(audio) / SAMPLE_RATE / 60:.1f} min of audio in {(time.time() - t0) / 60:.1f} min -> {out}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
