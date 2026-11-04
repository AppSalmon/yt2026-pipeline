#!/usr/bin/env python3
"""Demo: dùng Whisper (faster-whisper) cắt 1 file audio dài thành segment.

Minh hoạ cơ chế: Whisper tự chia segment qua các timestamp token; script này
lấy (start, end, text) của từng segment rồi cắt WAV bằng sox.

Usage:
    python3 whisper_segment_demo.py <audio_in> [out_dir]

Output (out_dir, mặc định = thư mục chứa audio_in):
    <base>.16k.wav               16 kHz mono PCM s16le (ffmpeg resample)
    <base>.segments.jsonl        {"id","start","end","duration","text"} mỗi dòng
    segments/<base>.trans.txt    "{id} {text}" mỗi dòng
    segments/<base>-<i>.wav      segment đã cắt bằng sox

Env:
    WHISPER_MODEL  tên model faster-whisper (mặc định "small")
    WHISPER_LANG   mã ngôn ngữ (mặc định "vi" — ĐỔI theo ngôn ngữ bạn crawl)
    PREVIEW        số dòng in ra màn hình (mặc định 20)
"""
import json
import os
import subprocess
import sys

from faster_whisper import WhisperModel


def main(argv):
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0 if len(argv) > 1 else 1

    src = os.path.abspath(argv[1])
    if not os.path.isfile(src):
        print(f"ERROR: không thấy file audio: {src}")
        return 1

    base = os.path.splitext(os.path.basename(src))[0]
    out = os.path.abspath(argv[2]) if len(argv) > 2 else os.path.dirname(src)
    segdir = os.path.join(out, "segments")
    model_name = os.environ.get("WHISPER_MODEL", "small")
    lang = os.environ.get("WHISPER_LANG", "vi")
    preview = int(os.environ.get("PREVIEW", "20"))
    os.makedirs(segdir, exist_ok=True)

    wav16 = os.path.join(out, f"{base}.16k.wav")

    # 1) resample -> 16 kHz mono PCM s16le (đầu vào pipeline cũng là 16 kHz)
    print(f"[1/3] ffmpeg resample -> {wav16}")
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "warning", "-i", src,
         "-ac", "1", "-ar", "16000", "-acodec", "pcm_s16le", wav16],
        check=True,
    )

    # 2) Whisper: chia segment (timestamp token) -> generator (start, end, text)
    print(f"[2/3] faster-whisper model={model_name} device=cpu "
          f"compute_type=int8 lang={lang}")
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(wav16, language=lang, beam_size=5)
    print(f"      detected language={info.language} "
          f"(prob={info.language_probability:.3f}), duration={info.duration:.2f}s")

    # 3) ghi jsonl + trans.txt + cắt wav bằng sox
    trans_path = os.path.join(segdir, f"{base}.trans.txt")
    jsonl_path = os.path.join(out, f"{base}.segments.jsonl")
    rows = []
    with open(trans_path, "w", encoding="utf-8") as tw, \
            open(jsonl_path, "w", encoding="utf-8") as jw:
        for i, seg in enumerate(segments):
            sid = f"{base}-{i}"
            out_wav = os.path.join(segdir, f"{sid}.wav")
            dur = seg.end - seg.start
            subprocess.run(
                ["sox", wav16, out_wav, "trim", f"{seg.start:.3f}", f"{dur:.3f}"],
                check=True,
            )
            text = seg.text.strip()
            tw.write(f"{sid} {text}\n")
            row = {"id": sid, "start": round(seg.start, 3),
                   "end": round(seg.end, 3), "duration": round(dur, 3),
                   "text": text}
            jw.write(json.dumps(row, ensure_ascii=False) + "\n")
            rows.append(row)

    print(f"[3/3] done: {len(rows)} segments -> {segdir}")
    print(f"      jsonl : {jsonl_path}")
    print(f"      text  : {trans_path}")
    print("-" * 70)
    print(f"{'id':<18}{'start':>8}{'end':>9}{'dur':>8}  text")
    print("-" * 70)
    for r in rows[:preview]:
        print(f"{r['id']:<18}{r['start']:>8.2f}{r['end']:>9.2f}"
              f"{r['duration']:>8.2f}  {r['text']}")
    if len(rows) > preview:
        print(f"... (+{len(rows) - preview} segment nữa, xem file jsonl/trans.txt)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
