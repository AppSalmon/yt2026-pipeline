# YouTube Speech Crawl Pipeline (English summary)

Audio-only acquisition pipeline for building **per-language ASR corpora from
YouTube**, structurally derived from [GigaSpeech2](https://github.com/SpeechColab/GigaSpeech2).
It was originally written for **Vietnamese (vi–en code-switch)**; everything
language-specific is now a configuration value, so a colleague can target Thai,
Indonesian, Burmese, Khmer… with a few environment variables.

> Core rule: **the repository holds code only.** Crawled audio and every derived
> artefact live outside the repo, controlled by a single file: [`config.env`](config.env).

## What it does

| Stage | Script | Output |
|---|---|---|
| Crawl (audio only, `--dateafter`, `/videos` + `/shorts` + `/streams`, livestream filter, `--write-info-json`) | `crawler/download_from_youtube.sh`, `crawler/crawl_all.sh` | `$DOWNLOAD_DIR/<channel>/…{webm,m4a}` + `*.info.json` |
| Convert + transcribe (ffmpeg → 16 kHz mono WAV, Whisper with multi-language keep-list) | `convert_transcribe/convert_and_transcribe.py` | `corpus/*.wav`, `*.txt` |
| Forced alignment (MMS CTC + uroman) | `force_alignment/force_align.sh` | `*_manifest.jsonl` |
| Token-level language ID / code-switch flag | `codeswitch/detect_codeswitch.py` | annotated manifest |
| Filter (charset, duration, upload-date, code-switch split) | `segmentation/filter_manifest.py` | `output_filter/{all,codeswitch}/*.jsonl` |
| Cut segments | `segmentation/segment.sh` | segmented corpus |
| Audit / QC / stats | `metadata/{build_index,audio_qc,stats}.py` | `index.jsonl`, `qc_flags.jsonl` |
| Package batches/units + ledger | `metadata/{make_batch,make_unit,corpus_ledger}.py` | `batch_NNN/`, `units/<unit>/` |
| Upload / verify / cleanup | `sync/*.sh` | Google Drive + HuggingFace, checksum verified |
| Scheduled driver | `cron/crawl_weekly.sh` | end-to-end run |

The production stage is **audio-only acquisition (W1–W8)**: crawl → QC → package →
upload → verify → ledger. The transcription/segmentation stages are implemented
and runnable, but are usually run later on GPU.

## Quick start

```shell
./scripts/install_system_deps.sh          # ffmpeg/ffprobe/sox/rclone, no sudo
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
./scripts/download_models.sh              # fastText lid.176.ftz
./scripts/check_env.sh                    # read-only environment check

cp crawler/channels.example.txt crawler/channels.txt   # then edit
EXTRA_OPTS="--playlist-items 1:3" BATCH_LABEL=pilot \
  ./crawler/crawl_all.sh crawler/channels.txt "" 2
python3 metadata/stats.py
```

## Another language

```shell
export LANG_CODE=th ACCEPT_LANGS=th,en ISO_639_2=tha
./crawler/crawl_all.sh crawler/channels_th.txt "" 2
```

Full checklist (10 places, only **one** requires a code edit — the charset
filter): [`docs/ADD_LANGUAGE.md`](docs/ADD_LANGUAGE.md).

## Documentation

- [`docs/SETUP.md`](docs/SETUP.md) — install & verify
- [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) — every env var
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — runbook
- [`docs/ADD_LANGUAGE.md`](docs/ADD_LANGUAGE.md) — new language
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — per-file roles
- [`docs/DATA_LAYOUT.md`](docs/DATA_LAYOUT.md) — data tree, dedup layers
- [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) — real errors & fixes
- [`docs/ETHICS_AND_LICENSE.md`](docs/ETHICS_AND_LICENSE.md) — YouTube ToS, copyright
- [`SECURITY.md`](SECURITY.md) — never commit cookies/tokens/audio

## Licence

Code: Apache-2.0 ([`LICENSE`](LICENSE)). Third-party components and models:
[`NOTICE`](NOTICE).
