"""
Unit tests for playwright_scraper.py pure/defensive helpers (offline).
Playwright itself is imported lazily inside launch_browser, so the module
imports without a browser. We test the block-detection logic (pure) and that
rotate_ip() is defensive when no proxy / no warp-cli is available.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import playwright_scraper as ps


class TestDetectBlock:
    def test_cloudflare(self):
        assert ps.detect_block("<html>Just a moment...</html>") == "cloudflare"

    def test_datadome(self):
        assert ps.detect_block("...geo.captcha-delivery.com...") == "datadome"

    def test_recaptcha(self):
        assert ps.detect_block("<script src='/recaptcha/api.js'>") == "recaptcha"

    def test_google_ratelimit(self):
        assert ps.detect_block("our systems have detected unusual traffic") == "google_ratelimit"

    def test_403_in_title(self):
        assert ps.detect_block("", "403 Forbidden") == "http_403"

    def test_404_error_title(self):
        assert ps.detect_block("", "404 Error - Not Found") == "http_404"

    def test_clean_page_none(self):
        assert ps.detect_block("<html><body>tracks listing</body></html>", "Beatport") is None

    def test_empty(self):
        assert ps.detect_block("", "") is None


class TestRotateIp:
    def test_residential_branch(self, monkeypatch):
        monkeypatch.setattr(ps.time, "sleep", lambda *_: None)
        monkeypatch.setenv("RESIDENTIAL_PROXY", "http://u:p@host:1")
        assert ps.rotate_ip() is True

    def test_no_proxy_no_warp_is_defensive(self, monkeypatch):
        monkeypatch.setattr(ps.time, "sleep", lambda *_: None)
        monkeypatch.delenv("RESIDENTIAL_PROXY", raising=False)
        import subprocess
        monkeypatch.setattr(subprocess, "run", lambda *_, **__: (_ for _ in ()).throw(FileNotFoundError()))
        assert ps.rotate_ip() is False
