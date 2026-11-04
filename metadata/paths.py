#!/usr/bin/env python3
"""Single source of truth for DATA paths (Python side, mirrors ../config.env).

Rules (do not break these):
  * Crawled/derived data must live OUTSIDE the repo — the repo holds code plus the
    non-reproducible dedup archives in crawler/log/audios_*.txt only.
  * Environment variables ALWAYS win over config.env values.
  * Hard-coded fallbacks below are the last resort so every script works standalone.

Usage:
    from paths import download_dir, dataset_dir, ledger_file
    print(download_dir())
"""
import os
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_ENV = REPO_ROOT / "config.env"

# Keep in sync with config.env (last-resort defaults only).
# $HOME-based so a fresh clone never points at somebody else's machine.
_FALLBACK = {
    "DATA_ROOT": os.path.expanduser("~/data"),
    "DOWNLOAD_DIR": os.path.expanduser("~/data/download_from_youtube"),
    "DATASET_DIR": os.path.expanduser("~/data/dataset"),
    "LEDGER_FILE": os.path.expanduser("~/data/corpus_ledger.jsonl"),
    "MIN_UPLOAD_DATE": "20260101",
    "TARGET_HOURS": "50000",
    "LANG_CODE": "vi",
    "ACCEPT_LANGS": "vi,en",
    "ISO_639_2": "vie",
    "GDRIVE_PARENT": "gdrive:corpus",
    "GDRIVE_REMOTE": "gdrive:corpus",
    "HF_ORG": "",
}

_TOKEN_RE = re.compile(
    r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^{}]*))?\}"     # ${VAR} or ${VAR:-default}
    r"|\$([A-Za-z_][A-Za-z0-9_]*)"                        # $VAR  (bare)
)
_CACHE = None


def _expand(raw, values, depth=0):
    """Expand ${VAR:-default}, ${VAR} and $VAR — env first, then earlier config lines.

    Defaults may themselves contain $VARS (e.g. ${DOWNLOAD_DIR:-$DATA_ROOT/xyz}),
    hence the recursive call with a small depth guard.
    """
    if depth > 5:
        return raw
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        raw = raw[1:-1]

    def repl(match):
        if match.group(1) is not None:
            name, default = match.group(1), match.group(2)
        else:
            name, default = match.group(3), None
        value = os.environ.get(name) or values.get(name)
        if value:
            return value
        if default is not None:
            return _expand(default, values, depth + 1)
        return ""

    return _TOKEN_RE.sub(repl, raw)


def load_config_env():
    """Parse ../config.env into a dict with shell-like expansion (cached)."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    values = {}
    try:
        text = CONFIG_ENV.read_text(encoding="utf-8")
    except OSError:
        text = ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        key = key.strip()
        if not key.replace("_", "").isalnum():
            continue
        values[key] = _expand(raw.strip(), values)
    _CACHE = values
    return values


def get(name, default=None):
    """Resolved string value: env > config.env > default."""
    value = os.environ.get(name) or load_config_env().get(name)
    if value:
        return value
    if default is not None:
        return default
    return _FALLBACK.get(name)


def get_path(name, default=None):
    raw = get(name, default)
    if not raw:
        raise KeyError(f"{name} is not configured (env/config.env/fallback all empty)")
    return Path(raw).expanduser()


def data_root():
    return get_path("DATA_ROOT")


def download_dir():
    return get_path("DOWNLOAD_DIR")


def dataset_dir():
    return get_path("DATASET_DIR")


def ledger_file():
    return get_path("LEDGER_FILE")


def min_upload_date():
    return get("MIN_UPLOAD_DATE")


def target_hours():
    return float(get("TARGET_HOURS"))


def allow_in_repo_download():
    return str(get("ALLOW_IN_REPO_DOWNLOAD", "0")).lower() in {"1", "true", "yes", "on"}


def in_repo(path):
    """True when `path` resolves inside the pipeline repo (guard against repo data)."""
    try:
        return Path(path).resolve().is_relative_to(REPO_ROOT)
    except (OSError, ValueError):
        return False


def require_outside_repo(path, what="download"):
    """Abort unless `path` is outside the repo or the override flag is set."""
    if in_repo(path) and not allow_in_repo_download():
        raise SystemExit(
            f"REFUSING to use '{path}' for {what}: it is INSIDE the repo "
            f"({REPO_ROOT}).\nData must stay outside the repo — set DOWNLOAD_DIR, "
            "or export ALLOW_IN_REPO_DOWNLOAD=1 to override deliberately."
        )
    return Path(path)


def ensure_dir(path):
    Path(path).mkdir(parents=True, exist_ok=True)
    return Path(path)


if __name__ == "__main__":  # quick self-check: python3 metadata/paths.py
    print(f"repo_root          = {REPO_ROOT}")
    print(f"config_env         = {CONFIG_ENV} (exists={CONFIG_ENV.exists()})")
    print(f"data_root          = {data_root()}")
    print(f"download_dir       = {download_dir()}  in_repo={in_repo(download_dir())}")
    print(f"dataset_dir        = {dataset_dir()}  in_repo={in_repo(dataset_dir())}")
    print(f"ledger_file        = {ledger_file()}")
    print(f"min_upload_date    = {min_upload_date()}")
    print(f"target_hours       = {target_hours()}")
    print(f"allow_in_repo      = {allow_in_repo_download()}")
