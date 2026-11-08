import contextlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'ops'))
from browser_bridge import BrowserBridge


class BrowserBridgeTests(unittest.TestCase):
    def setup_bridge(self,folder):
        items={str(i):{'id':i,'composition':'(A)','deliveryService':'yandex','hasLabel':True} for i in (1,2)}
        worker=SimpleNamespace(DATA=Path(folder),request=lambda path:json.dumps(items[path.split('/')[1]]).encode(),
            select_printer=lambda item:'Test printer',prepare=Mock(return_value=(None,None,{})),atomic_json=lambda path,value:path.write_text(json.dumps(value)),agent_lock=contextlib.nullcontext)
        app=SimpleNamespace(worker=worker,printer_names=['Test printer'],ui=lambda fn:fn(),render=Mock())
        bridge=BrowserBridge(app);bridge.ui=lambda fn:fn()
        return bridge,items

    def test_plan_deduplicates_and_never_prepares_or_prints(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge,items=self.setup_bridge(folder)
            plan=bridge.plan({'ids':[1,1,2],'mode':'carrier'})
            self.assertEqual(plan['count'],2);self.assertEqual(plan['separators'],0)
            bridge.worker.prepare.assert_not_called()

    def test_changed_last_item_is_skipped_and_plan_is_consumed(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge,items=self.setup_bridge(folder);plan=bridge.plan({'ids':[1,2],'mode':'carrier'})
            items['2']['composition']='(CHANGED)'
            # plan holds decoded copies from request, not mutable source values.
            with patch('print_actions._manual_batch_locked',return_value={'submitted':['1'],'failed':None}) as batch:
                result=bridge.print_plan({'plan':plan['plan']})
                self.assertEqual(result,{'submitted':1,'failed':False,'skipped':1})
                self.assertEqual([v['id'] for v in batch.call_args.args[1]],[1])
                with self.assertRaises(ValueError): bridge.print_plan({'plan':plan['plan']})

    def test_missing_label_and_sku_are_skipped_without_losing_valid_items(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge,items=self.setup_bridge(folder)
            items['2']['hasLabel']=False
            plan=bridge.plan({'ids':[1,2],'mode':'carrier'})
            self.assertEqual(plan['count'],1)
            self.assertIn('2',json.loads((Path(folder)/'manual-preparation-errors.json').read_text()))
            self.assertFalse((Path(folder)/'state.json').exists())

    def test_uncertain_allows_explicit_manual_plan_without_touching_state(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge,_=self.setup_bridge(folder);path=Path(folder)/'state.json'
            text=json.dumps({'activatedAt':123,'printed':{},'uncertain':{'1':{'status':'submitting'}}});path.write_text(text)
            plan=bridge.plan({'ids':[1]});self.assertEqual(plan['count'],1);self.assertEqual(plan['uncertain'],1)
            with patch('print_actions._manual_batch_locked',return_value={'submitted':['1'],'failed':None}) as batch:
                bridge.print_plan({'plan':plan['plan']});batch.assert_called_once()
            self.assertEqual(path.read_text(),text);bridge.worker.prepare.assert_called_once()

if __name__=='__main__': unittest.main()

class BackgroundWindowTests(unittest.TestCase):
    def test_restart_resumes_scope_without_moving_the_start_time(self):
        import threading
        from app import App
        from auto_print import set_auto_print
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder);set_auto_print(data,True,enabled_from=100)
            original=(data/'auto-print.json').read_bytes()
            app=SimpleNamespace(running=False,thread=None,worker=SimpleNamespace(DATA=data),
                printer=Mock(),printer_names=['Test printer'],auto_print=Mock(),stop_event=threading.Event(),save=Mock(),note=Mock(),pass_once=Mock())
            app.printer.get.return_value='Test printer'
            with patch('app.threading.Thread'):App.start(app,resume=True)
            self.assertEqual((data/'auto-print.json').read_bytes(),original)
            self.assertTrue(app.running)

    def test_closing_agent_window_hides_it_without_stopping_printing(self):
        from app import App
        root=Mock()
        app=SimpleNamespace(background_agent=True,root=root,settings_window=None)
        App.close(app)
        root.withdraw.assert_called_once()
        root.destroy.assert_not_called()
