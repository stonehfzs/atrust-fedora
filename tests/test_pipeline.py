import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import catalog
import adapt


class CatalogTests(unittest.TestCase):
    def test_latest_numeric_and_official_host(self):
        text="""{name:'Ubuntu_X86：2.5.9',url:'https://atrustcdn.sangfor.com/standard/linux/2.5.9/ubuntu/amd64/aTrustInstaller_amd64.deb'},
        {name:'Ubuntu_X86：2.5.16.50',url:'https://atrustcdn.sangfor.com/standard/linux/2.5.16.50/ubuntu/amd64/aTrustInstaller_amd64.deb'}"""
        self.assertEqual(catalog.latest(catalog.parse(text)),'2.5.16.50')
    def test_catalog_does_not_accept_untrusted_downloads(self):
        for url in ['http://atrustcdn.sangfor.com/standard/linux/2.5/ubuntu/amd64/aTrustInstaller_amd64.deb',
                    'https://attacker.example/package.deb',
                    'https://atrustcdn.sangfor.com/standard/linux/2.5/uos/arm64/aTrustInstaller_arm64.deb']:
            with self.assertRaises(ValueError):catalog.validated_url(url)
    def test_changed_patch_anchor_stops_publication(self):
        with self.assertRaises(adapt.UnsupportedUpstream):
            adapt.replace_exact('different upstream code','expected anchor','patch',1,'browser')


if __name__=='__main__':unittest.main()
