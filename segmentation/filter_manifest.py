import argparse
import json
import re
import string
from abc import ABC, abstractmethod
from pathlib import Path

# Adapted from GigaSpeech2 pipeline/segmentation/filter_manifest.py.
# Changes for the Vietnamese (vi-en code-switch) corpus:
#   - CharsetFilter (Thai)      -> VietnameseCharsetFilter (Vietnamese + Latin + digits)
#   - LanguageConfidenceFilter  -> kept only for --mode monolingual (upstream behaviour)
#   - new UploadDateFilter      -> defensive check using joined upload_date
#   - new CodeSwitchFilter      -> selects code-switch segments into a separate corpus
#
# >>> NGÔN NGỮ KHÁC: charset filter là phần DUY NHẤT phải sửa theo ngôn ngữ.
#     1) `VietnameseCharsetFilter` giữ Latin + dấu tiếng Việt (Latin Extended
#        Additional) và loại mọi script khác. Với tiếng Thái/Myanmar/Khmer… hãy
#        thêm block Unicode tương ứng vào `EXTRA` (xem docs/ADD_LANGUAGE.md,
#        bảng "Unicode range theo ngôn ngữ").
#     2) `--min-upload-date` nên truyền $MIN_UPLOAD_DATE (run_pipeline.sh đã làm).
#     Xem docs/ADD_LANGUAGE.md §3 để biết checklist đầy đủ.


class FilterStrategy(ABC):
    @abstractmethod
    def apply(self, line):
        pass


class VietnameseCharsetFilter(FilterStrategy):
    """Keep segments whose text stays within Latin letters (Vietnamese + English),
    digits, whitespace and common punctuation.

    Rejects other scripts (Thai, CJK, Cyrillic, ...), emoji and stray symbols.
    """

    LATIN = "a-zA-Z"
    # Vietnamese diacritics live in Latin-1 supplement + Latin Extended-A +
    # Latin Extended Additional; also keep curly quotes/dashes Whisper emits.
    EXTRA = (
        r"\u00C0-\u024F"
        r"\u1E00-\u1EFF"
        r"\u2013-\u2014"
        r"\u2018-\u201D"
        r"\u2026"
        r"\u00AB\u00BB"
    )

    def __init__(self, allow_punctuation=True):
        punct = re.escape(string.punctuation) if allow_punctuation else ""
        allowed = self.LATIN + self.EXTRA + r"\u0030-\u0039" + r"\s" + punct
        self.valid_pattern = re.compile(f"[^{allowed}]")

    def apply(self, line):
        return not self.valid_pattern.search(line["text"])


class LanguageConfidenceFilter(FilterStrategy):
    """Upstream filter: keep only monolingual segments (fastText on full text)."""

    def __init__(self, model_path, confidence_threshold=0.95):
        import fasttext

        self.model = fasttext.load_model(model_path)
        self.confidence_threshold = confidence_threshold

    def apply(self, line):
        labels, probabilities = self.model.predict(line["text"], k=1)
        return probabilities[0] >= self.confidence_threshold


class AudioDurationFilter(FilterStrategy):
    def __init__(self, min_keep_duration=1, max_keep_duration=30):
        self.min_keep_duration = min_keep_duration
        self.max_keep_duration = max_keep_duration

    def apply(self, line):
        return (
            line["duration"] >= self.min_keep_duration
            and line["duration"] <= self.max_keep_duration
        )


class UploadDateFilter(FilterStrategy):
    """Defensive layer: keep only segments whose video was published on/after
    min_upload_date (YYYYMMDD). Segments without joined metadata are kept but
    counted as 'unverified' by the runner."""

    def __init__(self, min_upload_date="20260101"):
        self.min_upload_date = min_upload_date

    def apply(self, line):
        upload_date = line.get("upload_date")
        if upload_date is None:
            return True  # unverified; runner reports the count
        return upload_date >= self.min_upload_date


class CodeSwitchFilter(FilterStrategy):
    """Select segments flagged as code-switch by detect_codeswitch.py."""

    def apply(self, line):
        return bool(line.get("is_codeswitch", False))


class ContentFilter:
    def __init__(self, strategies):
        self.strategies = strategies

    def __call__(self, line):
        for strategy in self.strategies:
            if not strategy.apply(line):
                return False
        return True


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True,
                        help="Directory with annotated manifests from detect_codeswitch.py")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=["both", "all", "codeswitch", "monolingual"],
                        default="both",
                        help="both: write 'all/' and 'codeswitch/' corpora; "
                             "monolingual: upstream behaviour (fastText on full text)")
    parser.add_argument("--lid-model-path", type=str, default=None,
                        help="fastText lid model; required only for --mode monolingual")
    parser.add_argument("--min-upload-date", type=str, default="20260101")
    parser.add_argument("--min-duration", type=float, default=2)
    parser.add_argument("--max-duration", type=float, default=30)
    return parser.parse_args()


def filter_manifests(input_dir, output_dir, common_filter, cs_filter=None,
                     write_all=True, write_cs=True):
    total_cnt = valid_cnt = cs_cnt = unverified_date = 0
    for manifest_path in sorted(input_dir.rglob("*.jsonl")):
        if manifest_path.name.startswith("filtered_"):
            continue  # never re-filter our own outputs
        out_name = "filtered_" + manifest_path.name.replace("annotated_", "")
        if write_all:
            out_all = output_dir / "all" / out_name
        if write_cs and cs_filter is not None:
            out_cs = output_dir / "codeswitch" / out_name

        with open(manifest_path, "r", encoding="utf-8") as reader:
            rows = [json.loads(line) for line in reader if line.strip()]
        total_cnt += len(rows)

        common_rows = [r for r in rows if common_filter(r)]
        valid_cnt += len(common_rows)
        unverified_date += sum(1 for r in common_rows if "upload_date" not in r)

        if write_all:
            out_all.parent.mkdir(parents=True, exist_ok=True)
            with open(out_all, "w", encoding="utf-8") as writer:
                for r in common_rows:
                    writer.write(json.dumps(r, ensure_ascii=False) + "\n")
        if write_cs and cs_filter is not None:
            cs_rows = [r for r in common_rows if cs_filter.apply(r)]
            cs_cnt += len(cs_rows)
            out_cs.parent.mkdir(parents=True, exist_ok=True)
            with open(out_cs, "w", encoding="utf-8") as writer:
                for r in cs_rows:
                    writer.write(json.dumps(r, ensure_ascii=False) + "\n")

    rate = 1 - valid_cnt / total_cnt if total_cnt else 0.0
    print(f"total segments: {total_cnt}, valid segments: {valid_cnt}, "
          f"filtered rate: {rate:.4f}")
    if write_cs:
        print(f"code-switch segments: {cs_cnt}")
    print(f"segments without upload_date (unverified 2026): {unverified_date}")


def main():
    args = parse_args()
    common_strategies = [
        VietnameseCharsetFilter(),
        AudioDurationFilter(args.min_duration, args.max_duration),
        UploadDateFilter(args.min_upload_date),
    ]

    if args.mode == "monolingual":
        if not args.lid_model_path:
            raise SystemExit("--mode monolingual requires --lid-model-path")
        common_strategies[1] = LanguageConfidenceFilter(args.lid_model_path, 0.99)
        filter_manifests(args.input_dir, args.output_dir, ContentFilter(common_strategies),
                         write_all=True, write_cs=False)
        return

    cs = CodeSwitchFilter() if args.mode in ("both", "codeswitch") else None
    filter_manifests(
        args.input_dir, args.output_dir, ContentFilter(common_strategies),
        cs_filter=cs,
        write_all=args.mode in ("both", "all"),
        write_cs=args.mode in ("both", "codeswitch"),
    )


if __name__ == "__main__":
    main()