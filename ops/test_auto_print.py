import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from auto_print import auto_print_enabled, set_auto_print


def worker(folder):
    spec=importlib.util.spec_from_file_location('test_auto_worker',Path(__file__).with_name('print-agent.py'))
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.DATA=Path(folder)
    return module


class AutoPrintTests(unittest.TestCase):
    def test_missing_corrupt_and_disabled_switch_never_requests_or_changes_history(self):
        with tempfile.TemporaryDirectory() as folder:
            w=worker(folder); state=w.DATA/'state.json'; original=b'{"activatedAt":17,"printed":{"1":{}},"uncertain":{"2":{}}}'
            state.write_bytes(original)
            w.request=lambda *_:self.fail('Disabled worker must not request CRM')
            for content in (None,'broken','{"enabled":"true"}','{"enabled":false}'):
                if content is not None: (w.DATA/'auto-print.json').write_text(content)
                with contextlib.redirect_stdout(io.StringIO()): result=w.run_once()
                self.assertTrue(result['paused']); self.assertEqual(state.read_bytes(),original)
                self.assertFalse((w.DATA/'last-run.json').exists())
    def test_switch_off_stops_between_orders_without_losing_pending_or_activation(self):
        with tempfile.TemporaryDirectory() as folder:
            w=worker(folder); set_auto_print(folder,True)
            items=[{'id':n,'createdAt':n,'composition':'(A)','hasLabel':True} for n in (1,2)]
            w.atomic_json(w.DATA/'state.json',{'activatedAt':0,'scanFrom':0,'pending':{},'printed':{},'uncertain':{}})
            def request(path,body=None):
                if path=='history': return b'{"printed":{},"uncertain":{}}'
                if path.startswith('leads?'): return json.dumps({'items':items}).encode()
                if path.startswith('item/'): return json.dumps(items[int(path.split('/')[1])-1]).encode()
                return b'{"claimed":true}'
            w.request=request; w.prepare=lambda *_args,**_kw:(None,None,{})
            submitted=[]
            def print_one(*_): submitted.append(1); set_auto_print(folder,False)
            w.print_label=print_one
            with contextlib.redirect_stdout(io.StringIO()): w.run_once()
            state=json.loads((w.DATA/'state.json').read_text())
            self.assertEqual(len(submitted),1); self.assertEqual(set(state['printed']),{'1'})
            self.assertEqual(set(state['pending']),{'2'}); self.assertEqual(state['activatedAt'],0)
            self.assertFalse(state['uncertain']); self.assertFalse(auto_print_enabled(folder))


if __name__=='__main__': unittest.main()
