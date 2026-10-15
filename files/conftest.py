"""Konfigurasi pytest untuk suite forwarder.

main.py mengeksekusi side-effect saat di-import: ia membaca sejumlah env var WAJIB
(ANALYZE_SECRET, WEBHOOK_SECRET, DATABASE_URL, TELEGRAM_*) dan membuat direktori
LOG_DIR. Env itu HARUS sudah ter-set sebelum `import main` dieksekusi test module.
conftest.py di root `files/` di-import pytest sebelum koleksi test, jadi di sinilah
tempat paling aman untuk menyiapkannya.
"""
import os
import sys
import tempfile
from pathlib import Path

# Pastikan direktori files/ (lokasi main.py & backtest.py) ada di sys.path supaya
# `import main` / `import backtest` resolve saat suite dijalankan dari mana pun.
_FILES_DIR = Path(__file__).resolve().parent
if str(_FILES_DIR) not in sys.path:
  sys.path.insert(0, str(_FILES_DIR))

# LOG_DIR default main.py = /data/webhooks (tidak writable lokal). Arahkan ke temp dir
# supaya LOG_DIR.mkdir(...) saat import tidak gagal.
_TEST_LOG_DIR = tempfile.mkdtemp(prefix="forwarder-test-logs-")

# DATABASE_URL dummy aman karena POOL dibuat dengan open=False (tak ada koneksi nyata
# saat import). Nilai lain cukup placeholder; test tidak menyentuh jaringan nyata.
os.environ["ANALYZE_SECRET"] = "test-analyze-secret"
os.environ["WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["DATABASE_URL"] = "postgresql://u:p@localhost:5432/db"
os.environ["TELEGRAM_BOT_TOKEN"] = "test-bot-token"
os.environ["TELEGRAM_WEBHOOK_SECRET"] = "test-telegram-secret"
os.environ["TELEGRAM_ALLOWED_CHAT_IDS"] = "123,456"
os.environ["LOG_DIR"] = _TEST_LOG_DIR
