import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock
from urllib.request import ProxyHandler


class TransportTest(unittest.TestCase):
    def test_server_requests_use_direct_https_without_system_proxy(self):
        spec=importlib.util.spec_from_file_location('transport_worker',Path(__file__).with_name('print-agent.py'))
        worker=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
        opener=MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value=b'{}'
        with patch.dict(os.environ,{'PRINT_AGENT_TOKEN':'a'*43}), patch.object(worker,'browser_client_id',return_value='b'*32), patch.object(worker,'build_opener',return_value=opener) as build:
            self.assertEqual(worker.request('history'),b'{}')
        proxy,redirect=build.call_args.args
        self.assertIsInstance(proxy,ProxyHandler)
        self.assertEqual(proxy.proxies,{})
        self.assertIsInstance(redirect,worker.NoRedirect)
        self.assertTrue(opener.open.call_args.args[0].full_url.startswith('https://snowbrick.ru/'))


if __name__=='__main__':
    unittest.main()

