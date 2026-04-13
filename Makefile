PYTHON := .venv/bin/python
SNAPSHOT_PATH := .snapshots/catalog_snapshot.json
OCR_EVAL_LIMIT ?= 100
OCR_EVAL_PER_SET ?= 1
OCR_EVAL_REPORT ?=

.PHONY: ocr-eval-snapshot
ocr-eval-snapshot:
	$(PYTHON) scripts/run_snapshot_eval.py --snapshot-out $(SNAPSHOT_PATH) --per-set $(OCR_EVAL_PER_SET) --limit $(OCR_EVAL_LIMIT) $(if $(OCR_EVAL_REPORT),--json-out $(OCR_EVAL_REPORT),)
