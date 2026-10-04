"""Scoped nurse workspace assets; other role dashboards retain their layout."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'ui' / 'nurse'


def install(templates):
    for name in ('nurse.html', 'nurse-base.html', 'ops-base.html', 'charge.html', 'wallboard.html', 'manager.html', 'escalation-settings.html'):
        templates[name] = (ROOT / name).read_text()


    templates['admin.html'] = templates['admin.html'].replace("{% block content %}", "{% block content %}{% include 'escalation-settings.html' %}", 1)

def asset(name):
    return (ROOT / name).read_text() + ((ROOT / ('operations.css' if name == 'workspace.css' else 'operations.js')).read_text() if name in ('workspace.css', 'workspace.js') else '') + ((ROOT / 'wallboard-repeat.js').read_text() if name == 'workspace.js' else '')
