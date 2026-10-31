import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from auto_print import auto_print_enabled, auto_print_scope, set_auto_print


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
            w=worker(folder); set_auto_print(folder,True,enabled_from=1)
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

    def test_each_enable_records_a_new_scope_and_restart_reads_the_same_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('auto_print.time.time',return_value=100.25): set_auto_print(folder,True)
            first=auto_print_scope(folder);self.assertEqual(first[0],101)
            self.assertEqual(auto_print_scope(folder),first)
            set_auto_print(folder,False);self.assertIsNone(auto_print_scope(folder))
            set_auto_print(folder,True,enabled_from=200.5)
            second=auto_print_scope(folder);self.assertEqual(second[0],201);self.assertNotEqual(first[1],second[1])

    def test_old_pending_and_late_label_on_old_order_are_not_printed_history_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            w=worker(folder);set_auto_print(folder,True,enabled_from=100.25)
            items={n:{'id':n,'createdAt':at,'composition':'(A)','hasLabel':True} for n,at in [(1,50),(2,100),(3,101),(4,102),(5,103)]}
            printed={'5':{'status':'submitted','at':90}};uncertain={'4':{'status':'submitting','at':91}}
            w.atomic_json(w.DATA/'state.json',{'activatedAt':17,'scanFrom':20,'pending':{'1':items[1]},'printed':printed,'uncertain':uncertain})
            paths=[];prepared=[];submitted=[]
            def request(path,body=None):
                paths.append(path)
                if path.startswith('leads?'):return json.dumps({'items':list(items.values())}).encode()
                if path.startswith('item/'):return json.dumps(items[int(path.split('/')[1])]).encode()
                return b'{"claimed":true}'
            w.request=request;w.sync_history=lambda:None
            def prepare(item,**_):prepared.append(item['id']);return None,item['id'],{}
            w.prepare=prepare;w.print_label=lambda image,*_:submitted.append(image)
            with contextlib.redirect_stdout(io.StringIO()),self.assertRaises(SystemExit):w.run_once()
            state=json.loads((w.DATA/'state.json').read_text())
            self.assertEqual(prepared,[3]);self.assertEqual(submitted,[3]);self.assertIn('leads?from=101',paths)
            self.assertNotIn('item/1',paths);self.assertNotIn('item/2',paths)
            self.assertEqual(state['activatedAt'],17);self.assertEqual(state['printed']['5'],printed['5']);self.assertEqual(state['uncertain'],uncertain)
            self.assertIn('1',state['pending'])

    def test_old_or_invalid_enabled_file_requires_explicit_reenable_without_printing(self):
        with tempfile.TemporaryDirectory() as folder:
            w=worker(folder);w.request=lambda *_:self.fail('No historical scan without a new scope')
            for value in ({'enabled':True},{'enabled':True,'enabledFrom':'bad','generation':'a'*32}):
                w.atomic_json(w.DATA/'auto-print.json',value)
                with contextlib.redirect_stdout(io.StringIO()):result=w.run_once()
                self.assertTrue(result['requiresActivation']);self.assertFalse((w.DATA/'state.json').exists())

    def test_changed_scope_during_preparation_never_prints_the_preceding_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            w=worker(folder);set_auto_print(folder,True,enabled_from=1)
            item={'id':1,'createdAt':10,'composition':'(A)','hasLabel':True}
            w.atomic_json(w.DATA/'state.json',{'activatedAt':0,'scanFrom':0,'pending':{},'printed':{},'uncertain':{}})
            w.sync_history=lambda:None
            w.request=lambda path,body=None:json.dumps({'items':[item]} if path.startswith('leads?') else item).encode()
            def prepare(*_,**__):
                set_auto_print(folder,False);set_auto_print(folder,True,enabled_from=20)
                return None,None,{}
            w.prepare=prepare;w.print_label=lambda *_:self.fail('Previous activation must stop')
            with contextlib.redirect_stdout(io.StringIO()):result=w.run_once()
            self.assertEqual(result['submitted'],0)

    def test_first_scan_after_a_delay_uses_click_time_and_not_process_start_time(self):
        with tempfile.TemporaryDirectory() as folder:
            w=worker(folder);set_auto_print(folder,True,enabled_from=100)
            paths=[];w.sync_history=lambda:None
            def request(path,body=None):paths.append(path);return b'{"items":[]}'
            w.request=request
            with contextlib.redirect_stdout(io.StringIO()):w.run_once()
            self.assertIn('leads?from=100',paths)
            self.assertEqual(json.loads((w.DATA/'state.json').read_text())['activatedAt'],100)


if __name__=='__main__': unittest.main()
