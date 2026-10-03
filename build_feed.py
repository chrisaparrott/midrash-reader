"""Build the podcast feed (docs/<book>/feed.xml) for every finished MP3, and upload new MP3s.

    .venv/Scripts/python build_feed.py            # feed only
    .venv/Scripts/python build_feed.py --upload   # also commit + push so the episodes go live

Free hosting: GitHub Pages serves docs/ — feed, cover and 48 kbps episode copies.
(Release assets were tried first; Apple Podcasts refused them — served as
application/octet-stream.) Apple Podcasts: Library > ... >
Follow a Show by URL, paste the feed URL.
"""
import argparse
import email.utils
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).parent
AUDIO_DIR = ROOT / "data" / "audio"
DOCS = ROOT / "docs"
OWNER, REPO = "chrisaparrott", "midrash-reader"
SITE = f"https://{OWNER}.github.io/{REPO}"

SHOWS = {
    "bereshit-rabbah": {
        "title": "Bereshit Rabbah",
        "about": "Midrash Bereshit Rabbah read aloud in English, one chapter per episode. "
                 "Text: The Sefaria Midrash Rabbah, 2022 (CC-BY), from Sefaria.org.",
        "source": "https://www.sefaria.org/Bereshit_Rabbah",
    },
}
# Episodes are dated one day apart from this date so apps list them in chapter order.
EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


def duration_seconds(mp3: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(mp3)],
                         capture_output=True, text=True, check=True).stdout
    return round(float(json.loads(out)["format"]["duration"]))


def make_cover(path: Path, title: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x1d2b4f:s=1400x1400",
                    "-vf", f"drawtext=text='{title}':fontcolor=0xf3e6c4:fontsize=120:x=(w-text_w)/2:y=(h-text_h)/2"
                           ":fontfile='C\\:/Windows/Fonts/georgia.ttf'",
                    "-frames:v", "1", str(path)], check=True)


def web_copy(src: Path, dest: Path) -> Path:
    """48 kbps mono copy for Pages: clear speech, and a whole book stays under Pages' 1 GB site limit."""
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        print("encoding", dest.name, flush=True)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-codec:a", "libmp3lame", "-b:a", "48k",
                        "-ac", "1", "-map_metadata", "0", "-id3v2_version", "3", str(dest)], check=True)
    return dest


def build(slug: str) -> None:
    show = SHOWS[slug]
    make_cover(DOCS / slug / "cover.jpg", show["title"])
    items = []
    for src in sorted((AUDIO_DIR / slug).glob("*.mp3")):
        mp3 = web_copy(src, DOCS / slug / "audio" / src.name)
        chapter = int(mp3.stem.rsplit("-", 1)[1])
        url = f"{SITE}/{slug}/audio/{mp3.name}"
        date = email.utils.format_datetime(EPOCH + timedelta(days=chapter))
        items.append(f"""    <item>
      <title>{escape(show['title'])} {chapter}</title>
      <itunes:episode>{chapter}</itunes:episode>
      <itunes:episodeType>full</itunes:episodeType>
      <guid isPermaLink="false">{slug}-{chapter:03d}</guid>
      <pubDate>{date}</pubDate>
      <enclosure url="{url}" length="{mp3.stat().st_size}" type="audio/mpeg"/>
      <itunes:duration>{duration_seconds(mp3)}</itunes:duration>
    </item>""")
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>{escape(show['title'])}</title>
    <link>{show['source']}</link>
    <description>{escape(show['about'])}</description>
    <language>en</language>
    <itunes:author>Sefaria English translation</itunes:author>
    <itunes:type>serial</itunes:type>
    <itunes:explicit>false</itunes:explicit>
    <itunes:block>Yes</itunes:block>
    <itunes:image href="{SITE}/{slug}/cover.jpg"/>
{chr(10).join(items)}
  </channel>
</rss>
"""
    (DOCS / slug / "feed.xml").write_text(feed, encoding="utf-8")
    print(f"{slug}: {len(items)} episodes -> {SITE}/{slug}/feed.xml")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upload", action="store_true")
    args = ap.parse_args()
    for slug in SHOWS:
        build(slug)
    if args.upload:
        publish_feeds()


def publish_feeds() -> None:
    """Commit and push only the feed, cover and episode files, so GitHub Pages serves the new episodes."""
    files = [str(p.relative_to(ROOT)) for p in DOCS.rglob("*") if p.suffix in (".xml", ".jpg", ".mp3")]
    subprocess.run(["git", "add", *files], cwd=ROOT, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
        print("feed already up to date")
        return
    msg = "Feed: add finished chapters\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n"
    subprocess.run(["git", "commit", "-q", "-F", "-"], input=msg, text=True, cwd=ROOT, check=True)
    subprocess.run(["git", "push", "-q"], cwd=ROOT, check=True)
    print("feed published")


if __name__ == "__main__":
    main()
