"""Exercise the real entrypoint with disposable non-secret fixture files."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WebConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        (root / 'api-token').write_text('fixture_management_token', encoding='utf8')
        (root / 'htpasswd').write_text('fixture:hash\n', encoding='utf8')
        self.output = root / 'generated.conf'
        script = (ROOT / 'deploy/40-product-workbench.sh').read_text(encoding='utf8')
        for original, replacement in {
            '/run/secrets/product_api_token': root / 'api-token',
            '/run/secrets/web_htpasswd': root / 'htpasswd',
            '/etc/product-workbench/nginx.conf.template': ROOT / 'deploy/nginx.conf.template',
            '/etc/nginx/conf.d/default.conf': self.output,
        }.items():
            script = script.replace(original, str(replacement))
        self.script = root / 'entrypoint.sh'
        self.script.write_text(script, encoding='utf8')

    def run_config(self, **kwargs):
        env = {**os.environ, **kwargs}
        return subprocess.run(['sh', str(self.script)], env=env, capture_output=True, text=True)

    def test_basic_is_default(self):
        result = self.run_config()
        self.assertEqual(result.returncode, 0, result.stderr)
        config = self.output.read_text()
        self.assertIn('auth_basic "ProductDataCenter"', config)
        self.assertIn('proxy_set_header Authorization $http_authorization', config)

    def test_lan_restricts_only_web_and_preserves_rpa(self):
        result = self.run_config(WEB_ACCESS_MODE='lan', WEB_TRUSTED_CIDR='192.168.0.0/24')
        self.assertEqual(result.returncode, 0, result.stderr)
        config = self.output.read_text()
        self.assertIn('auth_basic off;', config)
        self.assertEqual(config.count('allow 192.168.0.0/24; deny all;'), 4)
        upload = config.split('location = /api/v1/product-assets {', 1)[1].split('}', 1)[0]
        self.assertIn('client_max_body_size 10m;', upload)
        self.assertIn('proxy_set_header Authorization $product_web_authorization', upload)
        rpa = config.split('location /rpa/v1/ {', 1)[1].split('}', 1)[0]
        self.assertNotIn('deny all', rpa)
        self.assertIn('proxy_set_header Authorization $http_authorization', rpa)

    def test_invalid_and_public_networks_fail_closed(self):
        for cidr in ('0.0.0.0/0', '8.8.8.0/24', '192.168.0.0/8', '172.15.0.0/16',
                     '192.168.1.0/24;allow all;', 'not-a-network'):
            with self.subTest(cidr=cidr):
                self.assertNotEqual(self.run_config(WEB_ACCESS_MODE='lan', WEB_TRUSTED_CIDR=cidr).returncode, 0)


if __name__ == '__main__':
    unittest.main()
