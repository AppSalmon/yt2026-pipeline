#!/usr/bin/env python3
"""make_hf_card.py — sinh README.md (dataset card) cho 1 unit, dùng chung cho Drive + HF.

Bộ sinh đọc stats.json / manifest.jsonl / UNIT.json của unit nên **không bao giờ** phải
sửa tay số liệu. Chạy lại sau mỗi lần bổ sung file là ra card mới.

Usage:
    python3 metadata/make_hf_card.py --name <unit> \
        [--repo <hf-user>/<unit>] [--contact "email"] [--unit-hours 10000]

Bộ sinh tự đọc LANG_CODE / ISO_639_2 / LANG_NAME từ env (hoặc config.env) để điền
front matter (language, pretty_name, tags) và tiêu đề. Phần PROSE trong card viết
cho corpus tiếng Việt — nếu LANG_CODE != "vi" thì card in cảnh báo ngay đầu file;
sửa prose theo docs/ADD_LANGUAGE.md trước khi publish.
"""
import argparse
import json
import os
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

# --- Ngôn ngữ (env > config.env > default tiếng Việt) -------------------------
# Card này sinh metadata cho HF; với ngôn ngữ khác hãy export LANG_CODE/LANG_NAME/
# LANG_NAME_EN/ISO_639_2 (hoặc sửa config.env) rồi đọc docs/ADD_LANGUAGE.md.
LANG_CODE = paths.get("LANG_CODE", "vi")
LANG_ISO3 = paths.get("ISO_639_2", "vie")
LANG_NAME = os.environ.get("LANG_NAME", "Vietnamese")
LANG_NAME_EN = os.environ.get("LANG_NAME_EN", LANG_NAME)
LANG_FLAG = os.environ.get("LANG_FLAG", "🇻🇳" if LANG_CODE == "vi" else "🏳️")


def load(unit_dir):
    stats = json.loads((unit_dir / "stats.json").read_text(encoding="utf-8"))
    unit = json.loads((unit_dir / "UNIT.json").read_text(encoding="utf-8"))
    rows = [json.loads(l) for l in (unit_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    # files.txt = tat ca file thuoc unit (audio + info.json) -> so lieu chinh xac
    all_paths = [l.strip() for l in (unit_dir / "files.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    stats["file_counts"] = {
        "total": len(all_paths),
        "audio": sum(1 for p in all_paths if not p.endswith(".info.json")),
        "info_json": sum(1 for p in all_paths if p.endswith(".info.json")),
    }
    return stats, unit, rows


def human(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or u == "TB":
            return f"{n:.1f} {u}"
        n /= 1000


def gb(n):
    return f"{float(n or 0) / 1e9:.1f} GB"


def build(stats, unit, rows, args):
    tot = stats["totals"]
    hours = tot["hours"]
    durs = sorted(r["duration"] for r in rows)
    sizes = sorted(r["size"] for r in rows)
    n = len(rows)
    dates = sorted(r["upload_date"] for r in rows)
    per_ch = stats.get("per_channel", {})
    per_month = stats.get("per_month", {})
    short_le_10 = sum(1 for d in durs if d <= 10)
    long_ge_1800 = sum(1 for d in durs if d >= 1800)
    med = statistics.median(durs)
    L = []
    A = L.append
    # ---------------- front matter ----------------
    A("---")
    A("license: other")
    A("license_name: research-only")
    A("language:")
    A(f"- {LANG_ISO3}")
    A("task_categories:")
    A("- automatic-speech-recognition")
    A(f"pretty_name: \"{LANG_NAME} YouTube Speech Corpus — {unit['unit']}\"")
    A("size_categories:")
    A("- 10K<n<100M")
    A("tags:")
    # "audio" = FORCE modality (docs HF "Force set a dataset modality"): HF tự suy modality
    # từ file -> .webm (container video) bị gắn nhầm modality:video/image. Xem PROJECT_STATUS §23.7.
    A("- audio")
    A(f"- {LANG_NAME_EN.lower()}")
    A("- speech")
    A("- asr")
    A("- automatic-speech-recognition")
    A("- vietnamese-dialects")
    A("- code-switching")
    A("- noisy-speech")
    A("- spontaneous-speech")
    A("- youtube")
    A("- year_2026")
    A("---")
    A("")
    unit_no = unit["unit"].split("_")[-1] if "_" in unit["unit"] else "unit"
    title = unit["unit"].replace("_", " ").replace("yt2026", "yt2026 ·")
    A(f"# {LANG_NAME} YouTube Speech Corpus — `{unit['unit']}`")
    A("")
    if LANG_CODE != "vi":
        A(f"> ⚠️ **Card template.** Front matter (language / pretty_name / tags) đã điền theo "
          f"`LANG_CODE={LANG_CODE}`, nhưng phần mô tả bên dưới được viết cho corpus tiếng Việt. "
          f"Sửa prose theo `docs/ADD_LANGUAGE.md` trước khi publish unit cho ngôn ngữ khác.")
        A("")
    year_from = paths.min_upload_date()[:4]
    A(f"> ### {LANG_FLAG} {LANG_NAME} nói thật, thu từ YouTube — **chỉ video xuất bản từ "
      f"{year_from} trở đi**. Dữ liệu **có tiếng, không kịch bản**, để huấn luyện và đánh giá "
      f"**ASR {LANG_NAME}** trong điều kiện thực tế.")
    A(f"> ### {LANG_FLAG} Real, un-scripted {LANG_NAME_EN} speech harvested from YouTube — "
      f"**{year_from}+ uploads only**. Raw audio for training and evaluating "
      f"**{LANG_NAME_EN} ASR** under real-world conditions.")
    A("")
    A(f"*Generated {stats['created_utc'][:10]} · one unit = ~{args.unit_hours:,} h · "
      "more units on the way toward 50k–100k h.*")
    A("")
    A("> ### 🗓 2026-only by construction — this unit does **not** overlap older corpora")
    A(">")
    A("> Every clip here was **published on or after 2026-01-01**. That is a **hard filter applied at "
      "crawl time**, not a sample that happened to look recent, and the field is auditable per clip: "
      "`upload_date` in `manifest.jsonl`.")
    A(">")
    A("> If you are looking for Vietnamese speech, this is the **2026-onward slice** — it is disjoint "
      "from public corpora covering earlier material (GigaSpeech 1 covers 2018–2021, GigaSpeech 2 spans "
      "pre-2026 releases). Nothing in this repository is duplicated from those releases.")
    A("")
    A("## At a glance")
    A("")
    A("| | |")
    A("|---|---|")
    A(f"| **Hours of audio** | **{hours:,.1f} h** |")
    A(f"| Audio files | {n:,} (`.webm`, Opus 48 kHz mono, **no re-encoding**) |")
    A(f"| Channels | {tot['channels']:,} YouTube channels |")
    fc = stats["file_counts"]
    A(f"| Metadata files | {fc['info_json']:,} `info.json` (yt-dlp; {fc['total']:,} files total) |")
    A(f"| Total size | {gb(tot['bytes'])} |")
    A(f"| **Publication window** | **{stats['date_range']['first']} → {stats['date_range']['last']}** "
      f"— **2026-only** (hard filter ≥ {paths.min_upload_date()}) |")
    A(f"| Median clip | {med:.0f} s (min {durs[0]} s · max {durs[-1]} s) |")
    A(f"| Clips ≤ 10 s / ≥ 30 min | {short_le_10:,} / {long_ge_1800:,} |")
    A(f"| Mean / median file | {human(statistics.mean(sizes))} / {human(statistics.median(sizes))} |")
    A("")
    A("## Why this corpus")
    A("")
    A("Public Vietnamese speech corpora are small and skew towards **clean read speech**. Real users "
      "listen to commentary, news, religious talks, street interviews and live streams — with accents, "
      "code-switching to English, background noise and microphone artefacts.")
    A("")
    A("This corpus is built for that gap:")
    A("")
    A("- **Un-scripted, conversational** speech instead of read sentences.")
    A("- **Vietnamese ↔ English code-switching** happens naturally in modern Vietnamese media.")
    A("- **Full acoustic range**: phone calls, radio/TV, field recordings, screen-capture audio.")
    A("- **Documented provenance** per clip (`video_id`, `channel_id`, `upload_date`) so any item can "
      "be audited, reproduced or removed.")
    A("- **Disjoint from older corpora.** Restricting the crawl to 2026+ uploads means this slice does "
      "not duplicate the 2020–2025 Vietnamese material already covered elsewhere — useful when you "
      "combine sources without worrying about overlap.")
    A("")
    A("## What's inside")
    A("")
    A("```")
    A(f"audio/<channel_id>/<upload_date>#<title>#<channel_id>#<video_id>_<duration>.webm")
    A(f"audio/<channel_id>/<upload_date>#<title>#<channel_id>#<video_id>_<duration>.info.json")
    A("manifest.jsonl   ·  one JSON object per audio file")
    A("SHA256SUMS       ·  sha256sum -c compatible")
    A("files.txt        ·  plain list of all relative paths")
    A("stats.json       ·  totals, per-channel and per-month aggregates")
    A("used_ids.txt     ·  video_ids in this unit (frozen: no duplicates across units)")
    A("UNIT.json        ·  unit metadata and layout contract")
    A("```")
    A("")
    A("> **Note — audio only: no video, no image.** Every file above is an **audio-only Opus")
    A("> track** (YouTube `format 251`, **no re-encoding**) inside a **`.webm` (Matroska) container**.")
    A("> The `.webm` extension is only a container choice: this repository contains **zero video")
    A("> and zero image files**. The Hugging Face Hub auto-detects modality from file extensions,")
    A("> so it may display `modality:video` / `modality:image` tags — the true, intended modality")
    A("> is **audio** (also enforced by the `audio` tag in this card's metadata).")
    A("")
    A("### `manifest.jsonl` fields")
    A("")
    A("| field | meaning |")
    A("|---|---|")
    A("| `rel_path` | path relative to `audio/` |")
    A("| `audio_path` | path relative to the crawl root |")
    A("| `video_id` / `channel_id` | YouTube IDs (join with `https://www.youtube.com/watch?v=<video_id>`) |")
    A("| `upload_date` | `YYYYMMDD` — the enforced 2026 window |")
    A("| `duration` | seconds |")
    A("| `size` / `mtime` | bytes / unix mtime |")
    A("| `sha256` | integrity hash |")
    A("| `info_json_path` | matching yt-dlp metadata file |")
    A("")
    A("## How to use it")
    A("")
    A("**Stream/download one file**")
    A("")
    A("```python")
    A("from huggingface_hub import hf_hub_download")
    A("")
    A(f'path = hf_hub_download(repo_id="{args.repo}", repo_type="dataset",')
    A('                     filename="UC.../20260930#...#<video_id>_<dur>.webm")')
    A("```")
    A("")
    A("**Bulk download (filtered)**")
    A("")
    A("```bash")
    A(f'hf download {args.repo} --repo-type dataset --include "UCxxx/*" --local-dir ./subset')
    A("```")
    A("")
    A("**Verify integrity**")
    A("")
    A("```bash")
    A("sha256sum -c SHA256SUMS        # every file, sha256")
    A("```")
    A("")
    A("**Load the metadata**")
    A("")
    A("```python")
    A("import json")
    A("rows = [json.loads(l) for l in open('manifest.jsonl')]")
    A(f"print(len(rows), 'clips,', sum(r['duration'] for r in rows)/3600, 'hours')")
    A("```")
    A("")
    A("> This repo is a **raw-audio** release (not a `datasets`-loadable build). Fetch files with "
      "`hf_hub_download` / `hf download`, then build your own shards (tar/webdataset/parquet) locally.")
    A("")
    A("## Coverage")
    A("")
    A("| month | clips | hours |")
    A("|---|---:|---:|")
    for m, r in sorted(per_month.items()):
        A(f"| {m} | {r['files']:,} | {r['hours']:,.1f} |")
    A("")
    A("## Quality & limitations")
    A("")
    A("- **No transcripts.** This is the acquisition stage: audio + provenance only.")
    A("- **2026-only, by design.** Nothing published before 2026-01-01 is included. Verify per clip "
      "with `upload_date` in `manifest.jsonl`.")
    A("- **Selection bias.** Channels were harvested from a Vietnamese-language discovery list; it is not "
      "a demographically balanced sample.")
    A("- **Channel-level licensing varies.** Items inherit whatever rights their original creator holds; "
      "see *Terms of access*.")
    A("- **Content may change.** A channel owner can delete a video, in which case that item may be "
      "removed here after a notice.")
    A("- Partially downloaded (`*.part`) files are excluded by construction.")
    A("")
    A("## Ethics, provenance & Terms of access")
    A("")
    A("This corpus is **acquired by automated crawling of public YouTube** for **non-commercial "
      "research** on Vietnamese speech. By downloading or using it you agree to:")
    A("")
    A("1. Use it for **research only** — not for commercial products or services.")
    A("2. **Do not redistribute** it (or derived audio) as your own dataset or model release.")
    A("3. Comply with YouTube's Terms of Service and with the copyright law that applies to you.")
    A("4. Cite this corpus (see below) and this repository.")
    A("")
    A("**Provenance.** Every clip carries its `video_id`, `channel_id`, `upload_date` and the crawl "
      f"timestamp ({stats['created_utc'][:10]}); the original URL is reconstructible as "
      "`https://www.youtube.com/watch?v=<video_id>`.")
    A("")
    A("**Takedown.** Rights holders may ask for removal of specific items, whole channels, or the "
      "entire dataset. Requests are honoured — contact the repository owner and we will act within "
      "**7 days**. Because everything is keyed by `video_id`, removals are precise and reproducible.")
    A("")
    if args.contact:
        A(f"**Contact / takedown:** {args.contact}")
        A("")
    A("## Citation")
    A("")
    A("```bibtex")
    A(f"@misc{{{args.repo.split('/')[-1]},")
    A(f"  title  = {{{LANG_NAME_EN} YouTube Speech Corpus "
      f"({unit['unit'].split('_')[0]}) — raw audio for {LANG_NAME_EN} ASR}},")
    A(f"  note   = {{Unit {unit_no}, {hours:,.0f} hours, {n:,} clips, {tot['channels']} channels}},")
    A(f"  year   = {{{stats['created_utc'][:4]}}},")
    A(f"  url    = {{https://huggingface.co/datasets/{args.repo}}}")
    A("```")
    A("")
    A("## Roadmap")
    A("")
    A("- Transcribe (Whisper-family models) + forced alignment, released as separate repos.")
    A("- More units toward **50k–100k hours**; each unit is versioned, checksummed and gated.")
    A("")
    A("---")
    A("")
    A("*Generated by `metadata/make_hf_card.py` — do not edit by hand; re-run the generator instead.*")
    A("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True)
    ap.add_argument("--repo", default=None,
                    help="repo_id HF '<hf-user>/<unit>' (mặc định: $HF_ORG/<name>; "
                         "để trống cả hai => lỗi)")
    ap.add_argument("--contact", default="")
    ap.add_argument("--unit-hours", type=int, default=10000)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.repo:
        org = paths.get("HF_ORG", "") or ""
        if not org:
            raise SystemExit(
                "Cần biết repo HF: truyền --repo <hf-user>/<unit>, hoặc export "
                "HF_ORG=<hf-user> (xem config.env)."
            )
        args.repo = f"{org}/{args.name}"
    unit_dir = Path(paths.dataset_dir()) / "units" / args.name
    stats, unit, rows = load(unit_dir)
    md = build(stats, unit, rows, args)
    out = unit_dir / "README.md"
    if args.dry_run:
        print(md[:1500])
        return 0
    out.write_text(md, encoding="utf-8")
    print(f"README: {out} ({len(md)} chars, {md.count(chr(10))+1} dong)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
