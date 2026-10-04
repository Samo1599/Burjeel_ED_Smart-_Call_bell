"""Check the real served operations CSS in Chromium, across display modes."""
import unittest
import os
from playwright.sync_api import sync_playwright
import nurse_workspace


class WallboardAnimationBrowserTests(unittest.TestCase):
    def test_full_card_colors_change_and_completed_calls_stop(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get('WALLBOARD_TEST_CHROME'), args=['--no-sandbox'])
            page = browser.new_page()
            for width in (390, 1440):
                page.set_viewport_size({'width': width, 'height': 900})
                for mode in ('compact', 'cards', 'list', 'zones'):
                    page.set_content('<style>' + nurse_workspace.asset('workspace.css') + '</style><body class="ops-workspace"><div class="wall-room-grid view-' + mode + '"><article class="wall-room-card">ED-01</article></div></body>')
                    for stage in ('fresh', 'warning', 'critical', 'takeover'):
                        colors = page.evaluate('''stage => {
                            const card=document.querySelector('article');
                            card.className='wall-room-card alert-'+stage;
                            const animation=card.getAnimations()[0];
                            if(!animation) throw new Error('Missing animation: '+stage);
                            animation.pause(); animation.currentTime=0;
                            const low=getComputedStyle(card).backgroundColor;
                            animation.currentTime=animation.effect.getTiming().duration/2;
                            return [low,getComputedStyle(card).backgroundColor];
                        }''', stage)
                        self.assertNotEqual(*colors, (width, mode, stage))
                    for stage in ('arrived', 'idle'):
                        self.assertEqual(page.evaluate("stage=>{const c=document.querySelector('article');c.className='wall-room-card alert-'+stage;return getComputedStyle(c).animationName}", stage), 'none')
            browser.close()
