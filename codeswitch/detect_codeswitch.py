#!/usr/bin/env python3
"""Annotate forced-aligned manifests with per-segment language mixes.

Reads the *_manifest.jsonl files produced by force_alignment and adds:
  "languages":     {lang: token_ratio, ...}   (e.g. {"vi": 0.86, "en": 0.14})
  "is_codeswitch": True when >= 2 languages each cover >= --min-ratio tokens
  "n_tokens":      number of language-bearing tokens

Optionally joins video metadata (upload_date, channel, title) from the yt-dlp
*.info.json files (--info-root) so later stages can verify the 2026 constraint.

Per-token language ID is done with fastText lid.176; tokens shorter than 3
characters or with low confidence inherit the nearest confident neighbour.
"""
import argparse
import json
import os
import re
from collections import Counter
from pathlib import Path

LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)  # any unicode letter


def build_info_index(info_root):
    """Map youtube video id -> metadata, from all *.info.json under info_root."""
    index = {}
    for p in Path(info_root).rglob("*.info.json"):
        try:
            meta = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if meta.get("_type") == "playlist" or "entries" in meta:
            continue
        vid = meta.get("id")
        if not vid:
            continue
        index[vid] = {
            "video_id": vid,
            "upload_date": meta.get("upload_date"),
            "channel": meta.get("channel") or meta.get("uploader"),
            "channel_id": meta.get("channel_id"),
            "title": meta.get("title"),
            "webpage_url": meta.get("webpage_url"),
        }
    return index


def video_id_from_audio_path(audio_filepath):
    """Recover the youtube video id from our wav naming '{chan}__{id}_{duration}'.wav"""
    base = os.path.splitext(os.path.basename(audio_filepath))[0]
    core = base.split("__")[-1]
    for cand in [core.rsplit("_", 1)[0], core]:  # id may itself contain '_'
        yield cand


class CodeSwitchDetector:
    """Hybrid vi-en token LID:

    1. token contains Vietnamese diacritics          -> 'vi' (deterministic)
    2. pure-ASCII token:
         - Vietnamese ASCII stopword (function word) -> 'vi'
         - found in English dictionary               -> 'en'
    3. otherwise fastText LID on a +/-window context -> label when confident,
       else inherit the nearest confident neighbour.

    Pure fastText mislabels English loanwords in Vietnamese sentences
    (subword model absorbs the context), hence the dictionary tier.
    """

    VI_RANGES = (
        "\u00C0-\u00FF\u0100-\u024F\u1E00-\u1EFF"  # latin extended + additional
    )
    DIACRITIC_RE = re.compile(f"[{VI_RANGES}]")
    # Vietnamese function/stop words written WITHOUT diacritics that are also
    # valid English dictionary words (protects tier 2 from false positives).
    VI_ASCII_STOPWORDS = {
        "la", "va", "cho", "con", "nam", "nu", "on", "oi", "ma", "me", "mi",
        "mu", "sa", "ta", "te", "ti", "to", "tro", "tu", "ban", "ben", "cam",
        "can", "cap", "cat", "ca", "chi", "chung", "dam", "day", "den", "di",
        "do", "dong", "gap", "gay", "ha", "hang", "hoa", "ho", "hop", "hung",
        "kho", "le", "lien", "linh", "lo", "long", "lam", "lap", "luat", "mai",
        "man", "mot", "nap", "nao", "nho", "nhu", "noi", "phan", "phat",
        "phong", "qua", "quan", "ra", "sao", "sau", "so", "son", "thanh",
        "thai", "thu", "tinh", "toi", "tra", "trang", "tri", "trong",
        "truong", "tu", "vai", "van", "ve", "xin", "xem",
        # English loanwords fully assimilated into Vietnamese everyday speech
        "video", "internet", "email", "gmail", "google", "facebook", "youtube",
        "tiktok", "zalo", "xanh",
    }

    def __init__(self, lid_model_path, min_prob=0.6, min_ratio=0.10, min_tokens=4,
                 en_dict_path="/usr/share/dict/american-english", window=2):
        import fasttext

        self.model = fasttext.load_model(lid_model_path)
        self.min_prob = min_prob
        self.min_ratio = min_ratio
        self.min_tokens = min_tokens
        self.window = window
        self.en_dict = self._load_en_dict(en_dict_path)

    @staticmethod
    def _load_en_dict(path):
        words = set()
        candidates = []
        if path and os.path.exists(path):
            candidates.append(path)
        else:  # fall back to nltk corpus words
            try:
                from nltk.corpus import words as nltk_words

                words |= {w.lower() for w in nltk_words.words()}
            except Exception:
                pass
        for p in candidates:
            with open(p, encoding="utf-8", errors="ignore") as f:
                words |= {line.strip().lower() for line in f if "'" not in line}
        print(f"English dictionary loaded: {len(words)} words")
        return words

    def _in_en_dict(self, token):
        tok = token.lower()
        return tok in self.en_dict or (
            tok.endswith("s") and tok[:-1] in self.en_dict
        )

    def _window_label(self, tokens, i):
        win = " ".join(tokens[max(0, i - self.window): i + self.window + 1])
        labels, probs = self.model.predict(win, k=1)
        return labels[0].replace("__label__", ""), float(probs[0])

    def analyze(self, text):
        tokens = text.split()
        labels = [None] * len(tokens)

        # tiers 1-2: deterministic signals
        for i, tok in enumerate(tokens):
            if not LETTER_RE.search(tok):
                continue  # digits/punctuation: language neutral
            if self.DIACRITIC_RE.search(tok):
                labels[i] = "vi"
            elif self._in_en_dict(tok):
                labels[i] = (
                    "vi" if tok.lower() in self.VI_ASCII_STOPWORDS else "en"
                )

        # tier 3: window fastText, then neighbour inheritance
        for i, tok in enumerate(tokens):
            if labels[i] or not LETTER_RE.search(tok):
                continue
            lang, p = self._window_label(tokens, i)
            if p >= self.min_prob:
                labels[i] = lang
        conf_idx = [i for i, l in enumerate(labels) if l]
        for i, tok in enumerate(tokens):
            if labels[i] or not LETTER_RE.search(tok):
                continue
            left = next((j for j in reversed(conf_idx) if j < i), None)
            right = next((j for j in conf_idx if j > i), None)
            src = left if left is not None else right
            if src is not None:
                labels[i] = labels[src]

        tagged = [l for l in labels if l]
        if not tagged:
            return {"languages": {}, "is_codeswitch": False, "n_tokens": 0}

        counts = Counter(tagged)
        total = len(tagged)
        ratios = {l: round(c / total, 4) for l, c in counts.items()}
        present = [l for l, r in ratios.items() if r >= self.min_ratio]
        is_cs = total >= self.min_tokens and len(present) >= 2
        return {
            "languages": ratios,
            "is_codeswitch": bool(is_cs),
            "n_tokens": total,
        }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True,
                        help="Directory with *_manifest.jsonl from force_alignment")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--lid-model-path", type=str, required=True)
    parser.add_argument("--en-dict", type=str, default="/usr/share/dict/american-english",
                        help="English word list for loanword tier "
                        "(falls back to nltk corpus 'words')")
    parser.add_argument("--min-prob", type=float, default=0.6)
    parser.add_argument("--min-ratio", type=float, default=0.10,
                        help="Each language must cover >= this token ratio")
    parser.add_argument("--min-tokens", type=int, default=4,
                        help="Minimum language-bearing tokens to call code-switch")
    parser.add_argument("--info-root", type=str, default=None,
                        help="Download dir with yt-dlp *.info.json for metadata join")
    return parser.parse_args()


def main():
    args = parse_args()
    detector = CodeSwitchDetector(
        args.lid_model_path, args.min_prob, args.min_ratio, args.min_tokens,
        en_dict_path=args.en_dict,
    )
    info_index = build_info_index(args.info_root) if args.info_root else {}

    args.output_dir.mkdir(parents=True, exist_ok=True)
    total, cs_count, meta_hits = 0, 0, 0
    for manifest_path in sorted(args.input_dir.rglob("*.jsonl")):
        if manifest_path.name.startswith("annotated_"):
            continue
        out_path = args.output_dir / f"annotated_{manifest_path.name}"
        n_cs = 0
        with open(manifest_path, encoding="utf-8") as fin, \
                open(out_path, "w", encoding="utf-8") as fout:
            for line in fin:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                row.update(detector.analyze(row.get("text", "")))
                # join video metadata for the 2026 audit
                if info_index:
                    for vid in video_id_from_audio_path(row["audio_filepath"]):
                        if vid in info_index:
                            row["upload_date"] = info_index[vid]["upload_date"]
                            row["channel"] = info_index[vid]["channel"]
                            row["title"] = info_index[vid]["title"]
                            row["video_id"] = info_index[vid]["video_id"]
                            meta_hits += 1
                            break
                total += 1
                if row["is_codeswitch"]:
                    n_cs += 1
                fout.write(json.dumps(row, ensure_ascii=False) + "\n")
        cs_count += n_cs
        print(f"{manifest_path.name}: {n_cs} code-switch segments")

    rate = cs_count / total if total else 0.0
    print(f"total segments: {total}, code-switch: {cs_count} ({rate:.2%}), "
          f"metadata joined: {meta_hits}")


if __name__ == "__main__":
    main()