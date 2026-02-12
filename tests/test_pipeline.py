"""Tests for the extraction pipeline: mock extractor → normalizer → validator → writer."""
import sys, os, tempfile, pathlib
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from extractors.base import BaseExtractor, ExtractionResult
from normalizers.base import normalize, STANDARD_COLUMNS
from validators.schema import validate, ValidationError
from storage.csv_writer import write_csv


# ─── Mock Extractor ──────────────────────────────────────────────────────────

class MockBankExtractor(BaseExtractor):
    """Mock extractor for testing the pipeline."""

    @property
    def institution(self) -> str:
        return "Mock Bank"

    def extract(self, **kwargs) -> list[ExtractionResult]:
        df = pd.DataFrame({
            "date": ["2026-01-15", "2026-01-20", "2026-02-01"],
            "amount": [1500.00, 42.50, 200.00],
            "signed_amount": [1500.00, -42.50, -200.00],
            "description": ["DFAS SALARY", "NETFLIX", "AMAZON PURCHASE"],
            "category": ["Income", "Subscriptions", "Shopping"],
        })
        return [
            ExtractionResult(
                institution="Mock Bank",
                account="Checking",
                df=df,
                timestamp=datetime(2026, 2, 12),
                source="test",
            )
        ]


# ─── Tests ───────────────────────────────────────────────────────────────────

class TestExtractorBase:
    def test_mock_extractor_institution(self):
        ext = MockBankExtractor()
        assert ext.institution == "Mock Bank"

    def test_mock_extractor_repr(self):
        ext = MockBankExtractor()
        assert "MockBankExtractor" in repr(ext)

    def test_extract_returns_results(self):
        ext = MockBankExtractor()
        results = ext.extract()
        assert len(results) == 1
        assert results[0].row_count == 3


class TestNormalizer:
    def test_normalize_produces_standard_columns(self):
        df = pd.DataFrame({
            "date": ["2026-01-15"],
            "amount": [100.0],
            "signed_amount": [100.0],
            "description": ["TEST"],
        })
        result = normalize(df, "Test Bank", "Checking")
        assert set(STANDARD_COLUMNS).issubset(set(result.columns))

    def test_normalize_fills_missing_columns(self):
        df = pd.DataFrame({
            "date": ["2026-01-15"],
            "amount": [100.0],
        })
        result = normalize(df, "Test Bank", "Checking")
        assert "institution" in result.columns
        assert result["institution"].iloc[0] == "Test Bank"


class TestValidator:
    def test_valid_dataframe_passes(self):
        df = pd.DataFrame({
            "date": pd.to_datetime(["2026-01-15"]),
            "txn_date": pd.to_datetime(["2026-01-15"]),
            "amount": [100.0],
            "signed_amount": [100.0],
            "direction": ["Credit"],
            "description": ["TEST"],
            "category": ["Income"],
            "institution": ["Test"],
            "account": ["Checking"],
        })
        issues = validate(df)
        # Should have no issues besides possibly extra columns
        critical = [i for i in issues if "Missing" in i or "empty" in i.lower()]
        assert len(critical) == 0

    def test_missing_columns_detected(self):
        df = pd.DataFrame({"date": pd.to_datetime(["2026-01-15"])})
        issues = validate(df)
        assert any("Missing" in i for i in issues)

    def test_strict_mode_raises(self):
        df = pd.DataFrame({"foo": [1]})
        try:
            validate(df, strict=True)
            assert False, "Should have raised ValidationError"
        except ValidationError:
            pass


class TestCsvWriter:
    def test_write_and_read(self):
        df = pd.DataFrame({
            "date": pd.to_datetime(["2026-01-15"]),
            "amount": [100.0],
            "description": ["TEST"],
        })
        with tempfile.TemporaryDirectory() as tmpdir:
            path = write_csv(df, "Test Bank", "Checking",
                             pathlib.Path(tmpdir),
                             timestamp=datetime(2026, 2, 12))
            assert path.exists()
            assert "Test_Bank_Checking_20260212.csv" in path.name
            loaded = pd.read_csv(path)
            assert len(loaded) == 1


class TestEndToEndPipeline:
    """Full pipeline: extract → normalize → validate → write."""

    def test_full_pipeline(self):
        # 1. Extract
        ext = MockBankExtractor()
        results = ext.extract()
        assert len(results) == 1
        result = results[0]

        # 2. Normalize
        normalized = normalize(result.df, result.institution, result.account)
        assert set(STANDARD_COLUMNS).issubset(set(normalized.columns))

        # 3. Validate
        issues = validate(normalized)
        critical = [i for i in issues if "Missing" in i]
        assert len(critical) == 0, f"Validation failed: {issues}"

        # 4. Write
        with tempfile.TemporaryDirectory() as tmpdir:
            path = write_csv(normalized, result.institution, result.account,
                             pathlib.Path(tmpdir), result.timestamp)
            assert path.exists()

            # 5. Verify round-trip
            loaded = pd.read_csv(path)
            assert len(loaded) == 3
            assert "signed_amount" in loaded.columns
