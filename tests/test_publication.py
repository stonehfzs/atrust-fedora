import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import publish

class PublicationTests(unittest.TestCase):
    def manifest(self, root, fedora):
        name = f'cn.com.sangfor.atrust-2.5.16.50-7.local.fc{fedora}.x86_64.rpm'
        data = b'test package payload'
        (root / name).write_bytes(data)
        value = dict(schema=1, name='cn.com.sangfor.atrust', rpm=name,
                     tag=f'v2.5.16.50-7.local.fc{fedora}',
                     rpm_sha256=hashlib.sha256(data).hexdigest(),
                     checks={'missing_libraries': 0})
        (root / 'manifest.json').write_text(json.dumps(value))
        return value

    def test_target_release_and_digest(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            m = self.manifest(root, publish.CONFIG['fedora_release'])
            self.assertEqual(publish.verify_manifest(root), m)
            (root / m['rpm']).write_bytes(b'corrupted')
            with self.assertRaises(ValueError): publish.verify_manifest(root)

    def test_previous_fedora_is_not_published_to_new_index(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.manifest(root, publish.CONFIG['fedora_release'] - 1)
            with self.assertRaises(ValueError): publish.verify_manifest(root)
