"""Scoped nurse workspace assets; other role dashboards retain their layout."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'ui' / 'nurse'


def install(templates):
    for name in ('nurse.html', 'nurse-base.html'):
        templates[name] = (ROOT / name).read_text()


def asset(name):
    return (ROOT / name).read_text()
