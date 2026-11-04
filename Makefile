# ============================================================================
# Makefile — tiện ích kiểm tra repo. KHÔNG thay thế script pipeline.
#   make help | check | sh-check | py-check | secrets | smoke | deps | models | clean
# ============================================================================

.PHONY: help check sh-check py-check secrets smoke deps models clean

help:            ## Liệt kê các target
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-10s %s\n", $$1, $$2}'

check: sh-check py-check secrets  ## Toàn bộ kiểm tra tĩnh

sh-check:        ## bash -n mọi file .sh (bỏ qua uroman upstream dùng CRLF)
	@fail=0; for f in $$(git ls-files '*.sh' 2>/dev/null || find . -name '*.sh'); do \
	  case "$$f" in *utils/uroman/*) continue;; esac; \
	  bash -n "$$f" || { echo "FAIL $$f"; fail=1; }; done; \
	  [ $$fail -eq 0 ] && echo "OK  shell syntax" || exit 1

py-check:        ## py_compile mọi file .py
	@python3 -m compileall -q . >/dev/null && echo "OK  python syntax"

secrets:         ## Quét secret + PII trước khi commit
	@git rev-parse --git-dir >/dev/null 2>&1 || { echo "FAIL chưa phải git repo"; exit 1; }
	@! git grep -nIE 'hf_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH) PRIVATE KEY' \
	  && echo "OK  no secret" || { echo "FAIL secret found"; exit 1; }
	@! git grep -nIE '@gmail\.com|/home/[a-z]+/' \
	  && echo "OK  no PII" || { echo "FAIL PII found"; exit 1; }

smoke:           ## Kiểm tra resolve config (READ-ONLY)
	@python3 metadata/paths.py
	@bash -c '. ./config.env && echo "LANG_CODE=$$LANG_CODE ACCEPT_LANGS=$$ACCEPT_LANGS ISO_639_2=$$ISO_639_2"'
	@bash -c '. ./config.env && echo "DOWNLOAD_DIR=$$DOWNLOAD_DIR" && echo "DATASET_DIR=$$DATASET_DIR"'

deps:            ## Cài tool hệ thống (ffmpeg/ffprobe/sox/rclone, không sudo)
	./scripts/install_system_deps.sh

models:          ## Tải model LID (fastText lid.176.ftz)
	./scripts/download_models.sh

clean:           ## Xoá __pycache__ trong repo
	@find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	@echo "OK  cleaned"
