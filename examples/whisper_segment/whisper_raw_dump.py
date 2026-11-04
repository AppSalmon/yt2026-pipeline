#!/usr/bin/env python3
"""Dump RAW prediction của Whisper (faster-whisper):
  - token ids THÔ cho từng cửa sổ 30 s (trước khi chia segment)
  - token ids + chuỗi decode có <|timestamp|> cho từng segment
  - độ dài (giây) của từng timestamp token = time_precision (0.02 s)

Usage:
    python3 whisper_raw_dump.py <audio_in_16k.wav> [out_dir]

Nên chạy sau whisper_segment_demo.py (dùng file <base>.16k.wav do bước đó tạo).

Output (out_dir, mặc định = thư mục chứa audio_in):
    <base>.raw_windows.txt        raw token cho từng cửa sổ 30 s
    <base>.segments_tokens.txt    raw token cho từng segment

Env: WHISPER_MODEL (small) · WHISPER_LANG (vi)
"""
import os
import sys

from faster_whisper import WhisperModel
from faster_whisper.tokenizer import Tokenizer


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0 if len(argv) > 1 else 1

    wav16 = os.path.abspath(argv[1])
    if not os.path.isfile(wav16):
        print(f"ERROR: không thấy file audio: {wav16}")
        return 1

    base = os.path.splitext(os.path.basename(wav16))[0]
    if base.endswith(".16k"):          # <base>.16k.wav -> <base>
        base = base[: -len(".16k")]
    out = os.path.abspath(argv[2]) if len(argv) > 2 else os.path.dirname(wav16)
    model_name = os.environ.get("WHISPER_MODEL", "small")
    lang = os.environ.get("WHISPER_LANG", "vi")
    os.makedirs(out, exist_ok=True)

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    tok = Tokenizer(model.hf_tokenizer, model.model.is_multilingual,
                    task="transcribe", language=lang)
    print(f"timestamp_begin={tok.timestamp_begin} (= <|0.00|>), eot={tok.eot}, "
          f"time_precision={model.time_precision}s")

    # --- monkey-patch: bắt raw token của cả cửa sổ 30 s TRƯỚC khi chia segment ---
    raw_windows = []
    orig_split = model._split_segments_by_timestamps

    def spy(*a, **k):
        raw_windows.append(list(k["tokens"]))   # tokens = result.sequences_ids[0]
        return orig_split(*a, **k)

    model._split_segments_by_timestamps = spy

    segments, info = model.transcribe(wav16, language=lang, beam_size=5)
    seg_list = list(segments)

    # 1) raw window tokens
    p1 = os.path.join(out, f"{base}.raw_windows.txt")
    with open(p1, "w", encoding="utf-8") as f:
        f.write(f"# timestamp_begin={tok.timestamp_begin} (<|0.00|>), "
                f"mỗi token timestamp = {model.time_precision}s\n")
        f.write(f"# model={model_name} lang={lang} "
                f"language_prob={info.language_probability:.3f}\n")
        for wi, ids in enumerate(raw_windows):
            f.write(f"\n=== WINDOW {wi} | {len(ids)} tokens | raw ids ===\n")
            f.write(" ".join(map(str, ids)) + "\n")
            f.write("--- decoded with <|timestamps|> ---\n")
            f.write(tok.decode_with_timestamps(ids) + "\n")

    # 2) per-segment tokens
    p2 = os.path.join(out, f"{base}.segments_tokens.txt")
    with open(p2, "w", encoding="utf-8") as f:
        for s in seg_list:
            f.write(f"[{s.id}] {s.start:.2f}-{s.end:.2f}s ({s.end - s.start:.2f}s) "
                    f"no_speech={s.no_speech_prob:.3f}\n")
            f.write(f"  ids : {s.tokens}\n")
            f.write(f"  text: {tok.decode_with_timestamps(s.tokens)}\n")

    print(f"raw windows: {len(raw_windows)} | segments: {len(seg_list)}")
    print(f"-> {p1}")
    print(f"-> {p2}")

    if raw_windows:
        print("\n===== RAW PREDICT - WINDOW 0 (toàn bộ token trước khi chia segment) =====")
        w0 = raw_windows[0]
        print(f"số token: {len(w0)}")
        print("ids  :", " ".join(map(str, w0)))
        print("text :", tok.decode_with_timestamps(w0))
    for s in seg_list[:2]:
        print(f"\n[{s.id}] {s.start:.2f}-{s.end:.2f}s")
        print("  ids :", s.tokens)
        print("  text:", tok.decode_with_timestamps(s.tokens))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
