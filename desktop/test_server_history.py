import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from server_history import sync_history,merge_history

class HistoryTests(unittest.TestCase):
    def test_retry_upload_deduplicates_and_merge_preserves_local_uncertainty(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);posts=[]
            (root/'state.json').write_text(json.dumps({'printed':{'1':{'status':'submitted','at':10,'printer':'P'}},'uncertain':{'2':{'status':'submitting'}}}))
            remote={'printed':{'2':{'status':'submitted','at':20}},'uncertain':{},'events':[]}
            def request(path,body=None):
                if body: posts.extend(body['entries'])
                return json.dumps(remote).encode()
            worker=SimpleNamespace(DATA=root,request=request,atomic_json=lambda p,v:p.write_text(json.dumps(v)))
            before=(root/'state.json').read_bytes()
            sync_history(worker);sync_history(worker)
            self.assertEqual(len(posts),1)
            self.assertEqual((root/'state.json').read_bytes(),before)
            state=merge_history(root,json.loads(before))
            self.assertIn('2',state['uncertain'])
            self.assertTrue(state['printed']['2']['serverConfirmed'])
