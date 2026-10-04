"""The stylesheet actually served to operations must contain visual call alerts."""
import re
import unittest
import nurse_workspace


class WallboardStylesTests(unittest.TestCase):
    def test_served_styles_include_running_full_card_alerts(self):
        css = nurse_workspace.asset('workspace.css')
        for stage in ('fresh', 'warning', 'critical', 'takeover'):
            rules = re.findall(r'[^{}]*\.alert-' + stage + r'[^{}]*\{([^{}]*)\}', css)
            self.assertTrue(any('animation:' in rule and 'infinite' in rule for rule in rules), stage)
        self.assertIn('@keyframes wallboardCallPulse', css)
        self.assertIn('background-color:var(--wall-alert-high)', css)

    def test_completed_cards_explicitly_stop_animation(self):
        css = nurse_workspace.asset('workspace.css')
        self.assertRegex(css, r'alert-arrived[^{}]*\{[^{}]*animation:none')
        self.assertRegex(css, r'alert-idle[^{}]*\{[^{}]*animation:none')
