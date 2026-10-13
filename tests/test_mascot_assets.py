"""Validate the committed, local artwork containers; visual QA is separate."""
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]

class MascotAssetTests(unittest.TestCase):
    def png_size(self, name):
        data = (ROOT / 'ui/public/mascot' / name).read_bytes()
        self.assertLess(len(data), 1024 * 1024)
        self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(data[12:16], b'IHDR')
        return struct.unpack('>II', data[16:24])

    def test_atlas_is_eight_equal_64px_frames(self):
        self.assertEqual(self.png_size('atlas.png'), (256, 128))

    def test_brand_head_is_32px(self):
        self.assertEqual(self.png_size('head.png'), (32, 32))

    def test_base_icons_are_multisize_local_ico_files(self):
        for name in ('fox-idle', 'fox-working-1', 'fox-paused', 'fox-error'):
            with self.subTest(name=name):
                data = (ROOT / 'app/assets/fox-icons' / (name + '.ico')).read_bytes()
                self.assertLess(len(data), 1024 * 1024)
                reserved, kind, count = struct.unpack('<HHH',data[:6])
                self.assertEqual((reserved,kind),(0,1))
                self.assertGreaterEqual(count,5)
                self.assertLessEqual(count,10)
                sizes=set()
                for index in range(count):
                    entry=data[6+16*index:22+16*index]
                    w,h,_,_,_,_,length,offset=struct.unpack('<BBBBHHII',entry)
                    sizes.add((w or 256,h or 256))
                    self.assertGreaterEqual(offset,6+16*count)
                    self.assertGreater(length,0)
                    self.assertLessEqual(offset+length,len(data))
                self.assertTrue({(n,n) for n in (16,20,24,32,48)} <= sizes)
