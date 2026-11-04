> Docs index: [`docs/`](docs/) · Another language: [`docs/ADD_LANGUAGE.md`](docs/ADD_LANGUAGE.md) · Tiếng Việt: [`README.vi.md`](README.vi.md)

# Build a 50,000-Hour ASR Corpus from YouTube

**Multilingual · audio-only · audit-ready.** Harvests spontaneous speech from
YouTube and turns it into publishable ASR datasets: crawl → QC → package → verify
→ upload, with dedup and a checksum-verified ledger end to end.

> **49,149 hours already published** — 94,988 clips · 2,571 GB (≈2.39 TiB) ·
> 4 gated HuggingFace datasets. Numbers and links in
> [Published results](#published-results-reference-examples) below.

Built on [GigaSpeech2](https://github.com/SpeechColab/GigaSpeech2). Originally
written for **Vietnamese (vi–en code-switch)**; every language-specific part is now
a configuration value, so the same code targets Thai, Indonesian, Burmese, Khmer…
with a few environment variables.

> **Note:** personal side project, built outside working hours — not affiliated
> with any employer.

> Core rule: **the repository holds code only.** Crawled audio and every derived
> artefact live outside the repo, controlled by a single file:
> [`config.env`](config.env).

## What it does

```
crawler/download_from_youtube.sh   yt-dlp: audio-only, --dateafter $MIN_UPLOAD_DATE,
                                   livestream filter, crawls /videos + /shorts + /streams,
                                   --write-info-json (upload-date audit)
        │  $DOWNLOAD_DIR/<channel>/<date>#<title>#<channel_id>#<video_id>_<dur>.{webm,m4a}
        ▼
convert_transcribe/convert_and_transcribe.py
                                   ffmpeg → 16 kHz mono WAV + Whisper transcription
                                   (--accept-langs keeps several languages: code-switch safe)
        │  corpus/{<chan>__}{video_id}_{dur}.wav + .txt
        ▼
force_alignment/force_align.sh     MMS CTC forced alignment (torchaudio + uroman,
                                   ISO 639-2 = $ISO_639_2) → *_manifest.jsonl
        ▼
codeswitch/detect_codeswitch.py    token-level LID (fastText lid.176) → languages /
                                   is_codeswitch / upload_date in the manifest
        ▼
segmentation/filter_manifest.py    filters: language charset, duration 2–30 s,
                                   upload_date >= $MIN_UPLOAD_DATE
        │  output_filter/all/*.jsonl   and   output_filter/codeswitch/*.jsonl
        ▼
segmentation/segment.sh            cuts WAV files from the manifest → final segments
        │
        ▼
metadata/{stats,build_index,audio_qc}.py
                                   quick stats, index + upload-date audit, audio QC
metadata/{make_batch,make_unit,corpus_ledger}.py
                                   packaging (batch/unit) + dedup ledger
        ▼
sync/{upload_unit,upload_unit_hf,verify_unit,upload_hf_retry}.sh
                                   upload to Google Drive + HuggingFace, checksum verify
sync/cleanup_local.sh              deletes local data only when ledger.verified = true
cron/crawl_weekly.sh               scheduled driver (crawl → audit → QC → package →
                                   upload → verify → ledger → cleanup)
```

The stage in production use is **audio-only acquisition (W1–W8)**: crawl → QC →
package → upload → verify → ledger. The transcription/alignment/segmentation stages
are implemented and runnable, but are usually run later on GPU.

Per-file roles and the detailed diagram: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Quick start (5 minutes)

```shell
# 1) system tools (no sudo needed): ffmpeg + ffprobe + sox + rclone
./scripts/install_system_deps.sh

# 2) Python packages + LID model
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
./scripts/download_models.sh

# 3) environment check (READ-ONLY, ~10 checks)
./scripts/check_env.sh

# 4) your channel list
cp crawler/channels.example.txt crawler/channels.txt
$EDITOR crawler/channels.txt            # [name]<TAB>[@handle | channel/UCxxxx]

# 5) pilot crawl: 3 videos + 3 shorts per channel (data goes to $DOWNLOAD_DIR)
EXTRA_OPTS="--playlist-items 1:3" BATCH_LABEL=pilot \
  ./crawler/crawl_all.sh crawler/channels.txt "" 2

# 6) what do we have? files / hours / GB / per channel
python3 metadata/stats.py
```

Then run transcription → alignment → filtering → segmentation → index:

```shell
./run_pipeline.sh all
```


## Use it for another language

```shell
export LANG_CODE=th            # ISO 639-1 of the language you crawl
export ACCEPT_LANGS=th,en      # languages Whisper will KEEP (code-switch)
export ISO_639_2=tha           # 3-letter code for forced alignment / uroman

# 1) discovery keywords for that language
cp crawler/langs/vi/keywords.txt crawler/langs/th/keywords.txt   # then edit
python3 crawler/discover_channels.py \
  --keywords-file crawler/langs/th/keywords.txt \
  --num-per-keyword 40 --output crawler/candidates_th.tsv

# 2) review candidates_th.tsv → paste into crawler/channels_th.txt → check channels
./crawler/check_channels.sh crawler/channels_th.txt

# 3) crawl (format selector automatically uses [language^=th])
./crawler/crawl_all.sh crawler/channels_th.txt "" 2
```

**10-point checklist** (only **one** item needs a code edit — the charset filter)
→ [`docs/ADD_LANGUAGE.md`](docs/ADD_LANGUAGE.md).

## Published results (reference examples)

The first 4 units completed the full **crawl → QC → package → upload → verify**
chain. Use them to see what the output of this pipeline looks like.

| Unit | HuggingFace (gated: manual) | Hours | Audio files | GB (SI) | Channels |
|---|---|---|---|---|---|
| `yt2026_batch01_10kh` | https://huggingface.co/datasets/SalmonAI123/yt2026_batch01_10kh | 11,911.8 | 20,468 | 624.3 | 307 |
| `yt2026_batch02_10kh` | https://huggingface.co/datasets/SalmonAI123/yt2026_batch02_10kh | 11,884.0 | 17,754 | 624.7 | 320 |
| `yt2026_batch03_10kh` | https://huggingface.co/datasets/SalmonAI123/yt2026_batch03_10kh | 13,204.7 | 36,088 | 683.4 | 702 |
| `yt2026_batch04_10kh` | https://huggingface.co/datasets/SalmonAI123/yt2026_batch04_10kh | 12,148.5 | 20,678 | 638.7 | 436 |
| **Total** | 4 units | **49,149.0 h** | **94,988** | **2,571 GB ≈ 2.39 TiB** | — |

- Numbers come from `corpus_ledger.jsonl` (snapshot 2026-10-23) + the HF tree API (2026-11-04).
- **Uploaded 2026-01-01 onwards only** — auditable per clip via `upload_date` in
  `manifest.jsonl`; no overlap with corpora released before 2026.
- Datasets are **gated = manual** (you must accept on the HF page before downloading).
- Each unit ships `manifest.jsonl`, `files.txt`, `stats.json`, `SHA256SUMS` plus a
  dataset card generated by `metadata/make_hf_card.py` — exactly what this pipeline
  produces for your language.
- Audio is kept as the original `.webm` (Opus 48 kHz mono, **no re-encoding**), with
  the original `info.json` so every clip traces back to
  `https://www.youtube.com/watch?v=<video_id>`.

## Configuration

Everything is read from [`config.env`](config.env); exported environment variables
**always** win.

| Variable | Default | Meaning |
|---|---|---|
| `LANG_CODE` | `vi` | ISO 639-1 primary language (format selector + LID + HF card) |
| `ACCEPT_LANGS` | `$LANG_CODE,en` | languages Whisper keeps (code-switch) |
| `ISO_639_2` | `vie` | 3-letter code for forced alignment / uroman |
| `DATA_ROOT` | `$HOME/data` | root for all data (outside the repo) |
| `DOWNLOAD_DIR` | `$DATA_ROOT/download_from_youtube` | raw audio + `*.info.json` |
| `DATASET_DIR` | `$DATA_ROOT/dataset` | index, QC flags, batch/unit, hardlinks |
| `LEDGER_FILE` | `$DATA_ROOT/corpus_ledger.jsonl` | corpus ledger (dedup + verify state) |
| `MIN_UPLOAD_DATE` | `20260101` | only accept videos published on/after this date (YYYYMMDD) |
| `TARGET_HOURS` | `50000` | corpus size target (hours) |
| `MAX_VIDEOS` | `50` | max NEW videos per tab per run (`--max-downloads`) |
| `GDRIVE_PARENT` | `gdrive:corpus` | rclone destination on Google Drive |
| `HF_ORG` | (empty) | default HuggingFace account/organisation |

Full reference (30+ variables, exit codes, QC flags):
[`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).

## Documentation

The detailed docs are currently written in **Vietnamese** (the team's working
language); the English README is the entry point. Translations are welcome.

| File | Content |
|---|---|
| [`docs/SETUP.md`](docs/SETUP.md) | install from scratch (system tools, Python, models) + environment check |
| [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) | every configuration variable + precedence + exit codes |
| [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | runbook: crawl, monitor, QC, packaging, upload, verify, cleanup, cron |
| [`docs/ADD_LANGUAGE.md`](docs/ADD_LANGUAGE.md) | **add a new language** — 10 places to change |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | architecture, per-file roles, naming conventions |
| [`docs/DATA_LAYOUT.md`](docs/DATA_LAYOUT.md) | data tree, 3 dedup layers, server migration |
| [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) | real errors hit in production + fixes (429, cookies, HF, rclone, Xet…) |
| [`docs/ETHICS_AND_LICENSE.md`](docs/ETHICS_AND_LICENSE.md) | YouTube ToS, copyright, dataset release policy |
| [`SECURITY.md`](SECURITY.md) | what must **never** be committed |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | code conventions + change process |

Per-directory READMEs: [`crawler/cookies/`](crawler/cookies/README.md),
[`cron/`](cron/README.md), [`sync/`](sync/README.md),
[`force_alignment/`](force_alignment/README.md), [`models/`](models/README.md),
[`examples/whisper_segment/`](examples/whisper_segment/README.md).

## Warnings

- **YouTube ToS / copyright**: research use only; **do not redistribute** the raw
  audio. See [`docs/ETHICS_AND_LICENSE.md`](docs/ETHICS_AND_LICENSE.md).
- The repo contains **no** cookies, tokens, audio or private dataset links — see
  [`SECURITY.md`](SECURITY.md).
- Whisper can mis-transcribe code-switched speech; spot-check ~50 random segments
  before a large run.
- Storage: audio-only medium opus ≈ **42 MB/hour** ⇒ 10,000 hours ≈ 420 GB. Plan
  staging accordingly, or upload-and-delete per unit.

## Licence

Code: **Apache-2.0** ([`LICENSE`](LICENSE)). Reused components and third-party
models: [`NOTICE`](NOTICE) (GigaSpeech2 Apache-2.0, uroman MIT, fastText `lid.176`
CC-BY-SA 3.0).

Individual steps: `./run_pipeline.sh {crawl|convert|align|detect|filter|segment|index}`.
