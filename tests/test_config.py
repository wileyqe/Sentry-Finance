"""Tests for config.py — validates config.yaml loads correctly."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import cfg


class TestConfig:
    def test_data_sources_not_empty(self):
        assert len(cfg.data_sources) > 0

    def test_data_sources_have_required_keys(self):
        for src in cfg.data_sources:
            assert "path" in src
            assert "institution" in src
            assert "account" in src
            assert "loader" in src

    def test_excluded_categories(self):
        assert "Transfers" in cfg.excluded_categories
        assert "Savings" in cfg.excluded_categories

    def test_officiating_pattern(self):
        assert len(cfg.officiating_pattern) > 0

    def test_subscription_keywords(self):
        assert len(cfg.subscription_keywords) > 0
        assert "Netflix" in cfg.subscription_keywords

    def test_chase_keyword_map(self):
        assert isinstance(cfg.chase_keyword_map, dict)
        assert len(cfg.chase_keyword_map) > 0

    def test_colors(self):
        c = cfg.colors
        assert c.dark_bg.startswith("#")
        assert c.accent.startswith("#")

    def test_server(self):
        assert isinstance(cfg.server_port, int)
        assert isinstance(cfg.server_debug, bool)
