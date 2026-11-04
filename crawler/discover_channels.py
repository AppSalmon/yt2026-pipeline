#!/usr/bin/env python3
"""Discover conversational YouTube channels / recent videos for a language.

Searches YouTube with conversational keywords sorted by upload date
(full results URL with sp=CAI%3D — the ytsearchdate prefix was removed in
new yt-dlp), then extracts channel metadata.

Keywords come from (priority order):
    1. --keywords "..." "..."                  inline, ad-hoc
    2. --keywords-file <path>                  e.g. crawler/langs/th/keywords.txt
    3. crawler/langs/$LANG_CODE/keywords.txt   default per language
    4. built-in fallback list (Vietnamese)

Usage:
    python3 crawler/discover_channels.py --num-per-keyword 40 \
        --output crawler/candidates.tsv
    python3 crawler/discover_channels.py --keywords-file crawler/langs/th/keywords.txt \
        --num-per-keyword 40 --output crawler/candidates_th.tsv

Output TSV format (same as crawler/channels.txt): channel_name \t handle
"""
import argparse
import json
import os
import urllib.parse
from pathlib import Path

from yt_dlp import YoutubeDL

REPO_ROOT = Path(__file__).resolve().parent.parent

# Fallback khi chưa có file keywords cho ngôn ngữ đang crawl.
KEYWORDS = [
    "podcast tiếng việt",
    "talkshow việt nam",
    "phỏng vấn việt nam",
    "react việt nam",
    "vlog tiếng việt",
    "trò chuyện tiếng việt",
]


def read_keywords_file(path):
    """Đọc file keywords: mỗi dòng 1 từ khoá, dòng '#' là comment."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def default_keywords():
    """crawler/langs/<LANG_CODE>/keywords.txt nếu có, ngược lại dùng KEYWORDS."""
    lang = os.environ.get("LANG_CODE", "vi")
    for path in (REPO_ROOT / "crawler" / "langs" / lang / "keywords.txt",
                 Path(__file__).resolve().parent / "langs" / lang / "keywords.txt"):
        if path.is_file():
            kws = read_keywords_file(path)
            if kws:
                return kws
    return KEYWORDS

# sp=CAI%3D -> sort search results by upload date (newest first).
# (The old 'ytsearchdateN:' prefix was removed in yt-dlp >= 2026; full search
#  URLs via YoutubeSearchURLIE are the supported replacement.)
SEARCH_URL = "https://www.youtube.com/results?search_query={kw}&sp=CAI%3D"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keywords", nargs="*", default=None,
                        help="Từ khoá inline (mặc định: crawler/langs/$LANG_CODE/keywords.txt)")
    parser.add_argument("--keywords-file", type=str, default=None,
                        help="File keywords, mỗi dòng 1 từ khoá "
                             "(vd crawler/langs/th/keywords.txt)")
    parser.add_argument("--num-per-keyword", type=int, default=20)
    parser.add_argument(
        "--dateafter",
        type=str,
        default=os.environ.get("MIN_UPLOAD_DATE", "20260101"),
        help="Only keep videos uploaded on/after this date (YYYYMMDD). "
        "Default: $MIN_UPLOAD_DATE or 20260101.",
    )
    parser.add_argument("--output", type=str,
                        default=str(Path(__file__).resolve().parent / "channels_candidates.tsv"),
                        help="Output TSV path (default: crawler/channels_candidates.tsv)")
    return parser.parse_args()


def main():
    args = parse_args()

    keywords = args.keywords
    if args.keywords_file:
        keywords = read_keywords_file(args.keywords_file)
    elif not keywords:
        keywords = default_keywords()
    if not keywords:
        raise SystemExit("Không có từ khoá nào — dùng --keywords hoặc --keywords-file.")
    print(f"Keywords ({len(keywords)}): " + ", ".join(keywords))

    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "ignoreerrors": True,
        "playlist_items": f"1:{args.num_per_keyword}",
    }

    channels = {}
    for kw in keywords:
        url = SEARCH_URL.format(kw=urllib.parse.quote(kw))
        print(f"Searching: {kw}")
        try:
            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as e:
            print(f"  search failed: {e}")
            continue
        for entry in info.get("entries") or []:
            if not entry:
                continue
            up = entry.get("upload_date") or ""
            if up and up < args.dateafter:
                continue  # keep only 2026+ content
            cid = entry.get("channel_id")
            cname = entry.get("channel") or entry.get("uploader")
            if cid and cname and cid not in channels:
                channels[cid] = cname
                print(f"  found channel: {cname} (channel/{cid}, video {up})")

    with open(args.output, "w", encoding="utf-8") as f:
        f.write("# Discovered channels (review manually before adding to crawler/channels.txt)\n")
        for cid, cname in sorted(channels.items(), key=lambda x: x[1]):
            f.write(f"{cname}\tchannel/{cid}\n")
    print(f"Saved {len(channels)} candidate channels -> {args.output}")
    print(json.dumps({"total": len(channels)}, ensure_ascii=False))


if __name__ == "__main__":
    main()