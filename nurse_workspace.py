"""Scoped nurse workspace assets; other role dashboards retain their layout."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'ui' / 'nurse'


def install(templates):
    for name in ('nurse.html', 'nurse-base.html', 'ops-base.html', 'charge.html', 'wallboard.html', 'manager.html', 'escalation-settings.html'):
        templates[name] = (ROOT / name).read_text()


    admin = templates['admin.html']
    audit_nav = '      <button class="admin-nav-item" data-admin-tab="audit"'
    escalation_nav = '      <button class="admin-nav-item" data-admin-tab="escalation-settings" onclick="showAdminTab(\'escalation-settings\',this)">◷ <span>Escalation & Sound</span></button>\n'
    admin = admin.replace(audit_nav, escalation_nav + audit_nav, 1)
    overview = '<section class="admin-tab-pane active" id="admin-tab-overview">'
    escalation_pane = '<section class="admin-tab-pane" id="admin-tab-escalation-settings">{% include \'escalation-settings.html\' %}</section>\n    '
    admin = admin.replace(overview, escalation_pane + overview, 1)
    admin = admin.replace("['overview','staff','permissions','rooms','notifications','audit','system']", "['overview','staff','permissions','rooms','notifications','escalation-settings','audit','system']", 1)
    templates['admin.html'] = admin

def asset(name):
    return (ROOT / name).read_text() + ((ROOT / ('operations.css' if name == 'workspace.css' else 'operations.js')).read_text() if name in ('workspace.css', 'workspace.js') else '') + ((ROOT / 'wallboard-repeat.js').read_text() if name == 'workspace.js' else '')
