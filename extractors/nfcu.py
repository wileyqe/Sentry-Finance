"""
extractors/nfcu.py — Navy Federal Credit Union CSV extractor.

Wraps existing load_nfcu() loader into the BaseExtractor interface.
Future versions will add Playwright-based web scraping.
"""
import pathlib
import logging
from datetime import datetime

import pandas as pd

from extractors.base import BaseExtractor, ExtractionResult
from config import cfg

log = logging.getLogger("antigravity")


class NFCUExtractor(BaseExtractor):
    """Extracts Navy Federal data from CSV files.

    Currently reads from manually-downloaded CSVs defined in config.yaml.
    Designed to be extended with browser automation (Playwright) later.
    """

    @property
    def institution(self) -> str:
        return "Navy Federal"

    def extract(self, base_path: pathlib.Path | None = None, **kwargs) -> list[ExtractionResult]:
        """Load all NFCU accounts from config-defined CSV paths.

        Args:
            base_path: Project root directory. Defaults to current directory.
        """
        if base_path is None:
            base_path = pathlib.Path(".")

        from loaders import load_nfcu

        results = []
        for src in cfg.data_sources:
            if src["loader"] != "nfcu":
                continue

            path = base_path / src["path"]
            if not path.exists():
                log.warning("NFCU file not found: %s", path)
                continue

            try:
                df = load_nfcu(path, src["institution"], src["account"])
                results.append(ExtractionResult(
                    institution=src["institution"],
                    account=src["account"],
                    df=df,
                    timestamp=datetime.now(),
                    source=f"csv:{path.name}",
                ))
                log.info("NFCU extracted %d rows from %s", len(df), path.name)
            except Exception as e:
                log.error("Failed to extract NFCU %s: %s", path.name, e)

        return results
