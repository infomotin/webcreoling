"""
Automated End-to-End Demo Script.
Demonstrates the full pipeline workflow from raw URL crawling to specialized model evaluation and chat output.
"""

import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Ensure project root is on PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipeline import EndToEndNewsPipeline


def main():
    print("=" * 80)
    print("Starting WebCreoling End-to-End Bangla News Scraping & AI Pipeline Demo")
    print("=" * 80)

    runner = EndToEndNewsPipeline()
    results = runner.run_full_pipeline(
        use_mock_server=True,
        max_pages_per_category=2,
        base_train_epochs=1,
        finetune_epochs=2,
        interactive_chat=False,
    )

    print("\n" + "=" * 80)
    print("Demo Execution Completed Successfully!")
    print("=" * 80)


if __name__ == "__main__":
    main()
