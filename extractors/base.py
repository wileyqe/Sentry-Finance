"""
extractors/base.py — Base extractor interface for financial institutions.

All institution-specific extractors inherit from BaseExtractor.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
import pandas as pd


@dataclass
class ExtractionResult:
    """Result of a data extraction run."""
    institution: str
    account: str
    df: pd.DataFrame
    timestamp: datetime
    source: str  # e.g., "csv_upload", "api", "browser"
    row_count: int = 0

    def __post_init__(self):
        self.row_count = len(self.df)


class BaseExtractor(ABC):
    """Abstract base class for financial data extractors.

    Subclasses must implement:
      - institution: property returning institution name
      - extract(): method that returns ExtractionResult(s)
    """

    @property
    @abstractmethod
    def institution(self) -> str:
        """Human-readable institution name (e.g., 'Navy Federal')."""
        ...

    @abstractmethod
    def extract(self, **kwargs) -> list[ExtractionResult]:
        """Extract data from the institution.

        Returns a list of ExtractionResult objects (one per account).
        """
        ...

    def __repr__(self):
        return f"<{self.__class__.__name__} institution={self.institution!r}>"
