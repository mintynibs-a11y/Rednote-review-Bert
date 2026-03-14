.PHONY: setup run clean-data help

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*##"}; {printf "  %-18s %s\n", $$1, $$2}'

setup:  ## Install Python dependencies and Playwright Chromium
	pip install -r requirements.txt
	playwright install chromium

run:  ## Run the full pipeline with default settings
	python scripts/run_all.py

run-quick:  ## Run with limit=10 per platform (for quick testing)
	python scripts/run_all.py --limit-per-platform 10 --platforms bilibili,jd

run-no-sentiment:  ## Crawl only, skip sentiment analysis
	python scripts/run_all.py --skip-sentiment

clean-data:  ## Remove generated data files (keep directory structure)
	find data/raw data/clean data/output -name "*.json" -o -name "*.csv" -o -name "*.db" | xargs rm -f 2>/dev/null; true
	find logs -name "*.log" | xargs rm -f 2>/dev/null; true
	@echo "Data directories cleaned."
