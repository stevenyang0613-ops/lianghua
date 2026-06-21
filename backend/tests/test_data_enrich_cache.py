"""Tests for data_enrich cache loading with TTL validation"""
import json
import os
import time
import pytest
from pathlib import Path

from app.engine.data_enrich import _load_ext_cache


class TestLoadExtCacheTTL:
    """Test _load_ext_cache TTL (time-to-live) validation logic"""

    def setup_method(self):
        import tempfile
        self.tmpdir = Path(tempfile.mkdtemp())
        self.cache_path = self.tmpdir / "test_cache.json"

    def teardown_method(self):
        if self.cache_path.exists():
            self.cache_path.unlink()
        if self.tmpdir.exists():
            self.tmpdir.rmdir()

    def _write_cache(self, data: dict):
        with open(self.cache_path, "w") as fout:
            json.dump(data, fout)

    # --- Basic loading (ttl=0, no TTL check) ---

    def test_load_no_ttl_no_ts(self):
        self._write_cache({"600519": 1800.0})
        result = _load_ext_cache(self.cache_path, ttl=0)
        assert result == {"600519": 1800.0}

    def test_load_no_ttl_with_ts(self):
        self._write_cache({"600519": 1800.0, "_ts": time.time() - 99999})
        result = _load_ext_cache(self.cache_path, ttl=0)
        assert result.get("600519") == 1800.0

    def test_load_missing_file(self):
        result = _load_ext_cache(self.cache_path / "nonexistent.json", ttl=0)
        assert result == {}

    def test_load_invalid_json(self):
        self.cache_path.write_text("not valid json")
        result = _load_ext_cache(self.cache_path, ttl=0)
        assert result == {}

    def test_load_non_dict_json(self):
        with open(self.cache_path, "w") as fout:
            json.dump([1, 2, 3], fout)
        result = _load_ext_cache(self.cache_path, ttl=0)
        assert result == {}

    # --- TTL with _ts field ---

    def test_ttl_fresh_with_ts(self):
        self._write_cache({"600519": 1800.0, "_ts": time.time() - 100})
        result = _load_ext_cache(self.cache_path, ttl=3600)
        assert result.get("600519") == 1800.0

    def test_ttl_expired_with_ts(self):
        self._write_cache({"600519": 1800.0, "_ts": time.time() - 7200})
        result = _load_ext_cache(self.cache_path, ttl=3600)
        assert result == {}

    def test_ttl_zero_ts_falls_back_to_mtime(self):
        self._write_cache({"600519": 1800.0, "_ts": 0})
        result = _load_ext_cache(self.cache_path, ttl=3600)
        assert result.get("600519") == 1800.0

    # --- TTL with file mtime fallback ---

    def test_ttl_fresh_by_mtime(self):
        self._write_cache({"600519": 1800.0})
        result = _load_ext_cache(self.cache_path, ttl=3600)
        assert result.get("600519") == 1800.0

    def test_ttl_expired_by_mtime(self):
        self._write_cache({"600519": 1800.0})
        old_time = time.time() - 7200
        os.utime(self.cache_path, (old_time, old_time))
        result = _load_ext_cache(self.cache_path, ttl=3600)
        assert result == {}

    # --- Boundary cases ---

    def test_ttl_boundary_exactly_at_ttl(self):
        ts = time.time() - 3600
        self._write_cache({"600519": 1800.0, "_ts": ts})
        result = _load_ext_cache(self.cache_path, ttl=3600)
        assert result == {}

    def test_ttl_just_under_boundary(self):
        self._write_cache({"600519": 1800.0, "_ts": time.time() - 3599})
        result = _load_ext_cache(self.cache_path, ttl=3600)
        assert result.get("600519") == 1800.0

    def test_empty_dict_cache(self):
        self._write_cache({})
        result = _load_ext_cache(self.cache_path, ttl=0)
        assert result == {}

    def test_cache_with_only_ts(self):
        self._write_cache({"_ts": time.time()})
        result = _load_ext_cache(self.cache_path, ttl=3600)
        assert "_ts" in result
