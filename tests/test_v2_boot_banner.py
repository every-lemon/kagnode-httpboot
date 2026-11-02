import io
import os
import re
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'httpboot'))
from boot_ui import startup_banner,terminal_banner,Progress

class BootBannerTests(unittest.TestCase):
    def test_art_selects_a_layout_that_fits_without_wrapping(self):
        for width in (1,2,3,8,9,18,19,22,23,40,68,69,80,100,112,113,120,160):
            art=startup_banner(width)
            self.assertTrue(art.isascii())
            self.assertNotIn('\t',art)
            self.assertNotIn('\r',art)
            self.assertNotIn('\x1b',art)
            self.assertTrue(all(len(line)<width for line in art.splitlines()),(width,art))
        self.assertGreater(len(startup_banner(120)),len(startup_banner(80)))
    def test_redirected_startup_has_no_color_or_block_glyphs(self):
        output=io.StringIO()
        with patch('sys.stdout',output),patch.dict(os.environ,{'TERM':'xterm-256color','LANG':'en_US.UTF-8'}):
            progress=Progress()
            progress.close()
        self.assertNotIn('\x1b',output.getvalue())
        self.assertNotIn('█',output.getvalue())
        self.assertIn('HTTP Boot',output.getvalue())
    def test_color_does_not_change_glyphs_or_alignment(self):
        for width in (19,23,40,69,80,113,120):
            plain=terminal_banner(width,False,True)
            colored=terminal_banner(width,True,True)
            self.assertEqual(re.sub(r'\x1b\[[0-9;]*m','',colored),plain)
            self.assertTrue(all(len(line)<width for line in plain.splitlines()))
