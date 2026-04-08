"""Rolling generative fixtures for Sentry Finance dev/demo data.

The generator subpackage produces in-memory dictionaries that the seeder
(`scripts/seed_dummy_data.py`) feeds through the real upsert pipeline —
the same code path used by live connectors.

See `generator.py` for the entry points.
"""
