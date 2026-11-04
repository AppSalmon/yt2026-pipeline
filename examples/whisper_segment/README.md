# examples/whisper_segment — Whisper tự chia segment như thế nào

Hai script nhỏ, **độc lập với pipeline**, để hiểu cơ chế Whisper cắt audio dài
thành segment có timestamp (đây là lý do pipeline có thể dùng `segment.sh` để
cắt WAV theo manifest mà không cần aligner riêng):

| Script | Việc |
|---|---|
| `whisper_segment_demo.py` | resample 16 kHz → transcribe → ghi `*.segments.jsonl` + `*.trans.txt` + cắt từng segment bằng `sox` |
| `whisper_raw_dump.py` | dump **token thô** của từng cửa sổ 30 s và từng segment (để soi timestamp token, `time_precision=0.02 s`) |

## Chạy

```shell
pip install faster-whisper          # + ffmpeg, sox trong PATH

# 1) cắt segment
python3 examples/whisper_segment/whisper_segment_demo.py /path/to/audio.wav /tmp/out

# 2) soi token thô (dùng file 16 kHz do bước 1 tạo ra)
python3 examples/whisper_segment/whisper_raw_dump.py /tmp/out/audio.16k.wav /tmp/out
```

Biến môi trường: `WHISPER_MODEL` (mặc định `small`), `WHISPER_LANG` (mặc định
`vi` — **đổi theo ngôn ngữ bạn crawl**), `PREVIEW` (số dòng in ra, mặc định 20).

## Output

```
<output_dir>/
├── <base>.16k.wav            # 16 kHz mono PCM s16le (ffmpeg)
├── <base>.segments.jsonl     # {"id","start","end","duration","text"} mỗi dòng
├── <base>.raw_windows.txt    # (raw_dump) token thô từng cửa sổ 30 s
├── <base>.segments_tokens.txt# (raw_dump) token thô từng segment
└── segments/
    ├── <base>.trans.txt      # "{id} {text}" mỗi dòng (định dạng lhotse/kaldi-like)
    └── <base>-<i>.wav        # segment đã cắt
```

> Lưu ý: audio/transcript mẫu **không** được commit vào repo (bản quyền nội
> dung YouTube). Script tự tạo ra từ file bạn có quyền dùng.
