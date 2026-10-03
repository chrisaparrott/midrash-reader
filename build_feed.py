"""Build the podcast feed (docs/<book>/feed.xml) for every finished MP3, and upload new MP3s.

    .venv/Scripts/python build_feed.py            # feed only
    .venv/Scripts/python build_feed.py --upload   # also upload MP3s not yet on GitHub

Free hosting: MP3s are GitHub release assets (one release per book); the feed and
cover are served by GitHub Pages from docs/. Apple Podcasts: Library > ... >
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


def upload_new(slug: str, mp3s: list[Path]) -> None:
    repo = f"{OWNER}/{REPO}"
    r = subprocess.run(["gh", "release", "view", slug, "-R", repo, "--json", "assets"], capture_output=True, text=True)
    if r.returncode != 0:
        subprocess.run(["gh", "release", "create", slug, "-R", repo, "--title", SHOWS[slug]["title"],
                        "--notes", "Audio episodes."], check=True)
        have = set()
    else:
        have = {a["name"] for a in json.loads(r.stdout)["assets"]}
    for mp3 in mp3s:
        if mp3.name not in have:
            print("uploading", mp3.name, flush=True)
            subprocess.run(["gh", "release", "upload", slug, str(mp3), "-R", repo], check=True)


def build(slug: str, upload: bool) -> None:
    show = SHOWS[slug]
    mp3s = sorted((AUDIO_DIR / slug).glob("*.mp3"))
    if upload:
        upload_new(slug, mp3s)
    make_cover(DOCS / slug / "cover.jpg", show["title"])
    items = []
    for mp3 in mp3s:
        chapter = int(mp3.stem.rsplit("-", 1)[1])
        url = f"https://github.com/{OWNER}/{REPO}/releases/download/{slug}/{mp3.name}"
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
        build(slug, args.upload)
    if args.upload:
        publish_feeds()


def publish_feeds() -> None:
    """Commit and push only the feed files, so GitHub Pages serves the new episodes."""
    feeds = [str(p.relative_to(ROOT)) for p in DOCS.glob("*/*") if p.suffix in (".xml", ".jpg")]
    subprocess.run(["git", "add", *feeds], cwd=ROOT, check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
        print("feed already up to date")
        return
    msg = "Feed: add finished chapters\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n"
    subprocess.run(["git", "commit", "-q", "-F", "-"], input=msg, text=True, cwd=ROOT, check=True)
    subprocess.run(["git", "push", "-q"], cwd=ROOT, check=True)
    print("feed published")


if __name__ == "__main__":
    main()
