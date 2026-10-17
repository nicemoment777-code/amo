import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'ops'))
from orders_model import order_groups, parse_period, sku_color, print_status, order_title
from print_actions import manual_print
from printer_routing import normalize_routes, choose_printer, load_routes, PrinterRoutingError
from printer_panel import routes_from_rows, EMPTY_PRINTER

class BoardTests(unittest.TestCase):
    def test_article_filter_matches_any_selected_sku_without_duplicate_cards(self):
        import copy
        values=[{'id':1,'createdAt':5,'composition':'(A); (B)','hasLabel':True},
                {'id':2,'createdAt':5,'composition':'(C)','hasLabel':True},
                {'id':3,'createdAt':5,'composition':'нет артикула','hasLabel':False}]
        state={'printed':{'1':{'status':'submitted'}},'uncertain':{'2':{}}}
        before=copy.deepcopy((values,state))
        selected=order_groups(values,0,10,state,selected_skus={'A','B'})
        self.assertEqual([v['id'] for group in selected for v in group['items']],[1])
        self.assertEqual(selected[0]['skus'],('A','B'))
        self.assertEqual(order_groups(values,0,10,state,selected_skus=set()),[])
        unknown=order_groups(values,0,10,state,selected_skus={None})
        self.assertEqual(unknown[0]['items'][0]['id'],3)
        self.assertEqual((values,state),before)

    def test_date_and_article_filters_apply_together(self):
        values=[{'id':1,'createdAt':5,'composition':'(A)','hasLabel':True},
                {'id':2,'createdAt':15,'composition':'(A)','hasLabel':True}]
        selected=order_groups(values,10,20,{},selected_skus={'A'})
        self.assertEqual(selected[0]['items'][0]['id'],2)
    def test_crm_order_number_is_distinct_from_internal_lead_id(self):
        self.assertEqual(order_title({'id':41954135,'orderNumber':'001048'}),'№ 001048')
        self.assertEqual(order_title({'id':41954135}),'amo 41954135')
    def test_filter_dates_are_moscow_inclusive_and_groups_stay_together(self):
        start,end=parse_period('17.10.2026','00:00','17.10.2026','23:59')
        self.assertEqual(end-start,86399)
        values=[{'id':n,'createdAt':at,'composition':sku,'hasLabel':True} for n,at,sku in [
            (1,start,'(A)'),(2,end,'(B)'),(3,start+10,'(B)'),(4,end+1,'(A)')]]
        groups=order_groups(values,start,end,{'printed':{'2':{'status':'submitted'}}})
        self.assertEqual([[v['id'] for v in g['items']] for g in groups],[[3,2],[1]])
        self.assertEqual([v['confirmed'] for v in groups[0]['items']],[False,True])
        with self.assertRaises(ValueError): parse_period('17.10.2026','18:00','17.10.2026','17:00')

    def test_uncertain_or_server_reservation_never_shows_green(self):
        self.assertFalse(print_status(1,{'printed':{'1':{'status':'reserved-on-server'}}})[0])
        self.assertFalse(print_status(1,{'printed':{'1':{'status':'submitted'}},'uncertain':{'1':{}}},{'1':'submitted'})[0])
        self.assertTrue(print_status(1,{}, {'1':'submitted'})[0])

    def test_color_is_stable_and_multi_sku_card_is_not_duplicated(self):
        self.assertEqual(sku_color(('1-wsblue',)),sku_color(('1-wsblue',)))
        self.assertNotEqual(sku_color(('1-wsblue',)),sku_color(('1-sgreen',)))
        groups=order_groups([{'id':1,'createdAt':5,'composition':'(B); (A); (A)','hasLabel':True}],0,10,{})
        self.assertEqual(groups[0]['skus'],('A','B'))
        self.assertEqual(len(groups[0]['items']),1)

class FakeWorker:
    def __init__(self,folder,fail=False): self.DATA=Path(folder); self.fail=fail; self.calls=[]
    def agent_lock(self):
        from contextlib import nullcontext
        return nullcontext()
    def request(self,path,body=None):
        self.calls.append(path)
        if path.startswith('item/'): return json.dumps({'id':1,'hasLabel':True,'composition':'(A)'}).encode()
        return b'{"claimed":false}'
    def prepare(self,*args,**kwargs): return None,None,{}
    def select_printer(self,item): return 'Test printer'
    def atomic_json(self,path,value): path.write_text(json.dumps(value),encoding='utf-8')
    def print_label(self,*args):
        state=json.loads((self.DATA/'state.json').read_text())
        assert '1' in state['uncertain']
        if self.fail: raise RuntimeError('simulated driver error')

class ManualPrintTests(unittest.TestCase):
    def test_changed_assignment_does_not_print_on_unconfirmed_printer(self):
        with tempfile.TemporaryDirectory() as folder:
            w=FakeWorker(folder)
            with self.assertRaises(ValueError): manual_print(w,1,'Different printer')
            self.assertEqual(w.calls,['item/1'])
            self.assertFalse((w.DATA/'state.json').exists())
    def test_manual_print_preserves_activation_other_history_and_uncertain(self):
        with tempfile.TemporaryDirectory() as folder:
            w=FakeWorker(folder)
            w.atomic_json(w.DATA/'state.json',{'activatedAt':10,'scanFrom':20,'pending':{'1':{}},'printed':{'7':{'status':'submitted'}},'uncertain':{'8':{}}})
            manual_print(w,1)
            s=json.loads((w.DATA/'state.json').read_text())
            self.assertEqual((s['activatedAt'],s['scanFrom']),(10,20))
            self.assertEqual(set(s['printed']),{'1','7'}); self.assertEqual(set(s['uncertain']),{'8'})
            self.assertFalse(s['pending']); self.assertEqual(w.calls,['item/1','claim','complete'])

    def test_ambiguous_print_stays_uncertain_without_second_submission(self):
        with tempfile.TemporaryDirectory() as folder:
            w=FakeWorker(folder,fail=True)
            with self.assertRaises(RuntimeError): manual_print(w,1)
            s=json.loads((w.DATA/'state.json').read_text())
            self.assertIn('1',s['uncertain']); self.assertNotIn('1',s['printed'])
            self.assertNotIn('complete',w.calls)

class RoutingTests(unittest.TestCase):
    def test_four_rows_ignore_blank_slots_and_validate_duplicate_ownership(self):
        rows=[('P1',['A','B']),('P2',['C']),(EMPTY_PRINTER,[]),(EMPTY_PRINTER,[])]
        config=routes_from_rows(rows)
        self.assertEqual(config,{'enabled':True,'routes':[{'printer':'P1','skus':['A','B']},{'printer':'P2','skus':['C']}]})
        with self.assertRaises(PrinterRoutingError): routes_from_rows([('P1',['A']),('P2',['A'])])
        with self.assertRaises(PrinterRoutingError): routes_from_rows([(EMPTY_PRINTER,['A'])])
        with self.assertRaises(PrinterRoutingError): routes_from_rows([('P1',['A']),('P1',['B'])])
        self.assertEqual(routes_from_rows([(EMPTY_PRINTER,[])]*4),{'enabled':True,'routes':[]})
    def test_one_printer_can_have_multiple_articles_but_article_has_one_owner(self):
        routes={'routes':[{'printer':'P1','skus':['A','B']},{'printer':'P2','skus':['C']}]}
        self.assertEqual(choose_printer({'composition':'(A); (B)'},routes,'default'),'P1')
        self.assertEqual(choose_printer({'composition':'(C)'},routes,'default'),'P2')
        with self.assertRaises(PrinterRoutingError):
            normalize_routes({'routes':[{'printer':'P1','skus':['A']},{'printer':'P2','skus':['A']}]})

    def test_unassigned_and_mixed_printer_order_is_blocked_not_duplicated(self):
        routes={'routes':[{'printer':'P1','skus':['A']},{'printer':'P2','skus':['B']}]}
        for text in ['(C)','(A); (B)']:
            with self.assertRaises(PrinterRoutingError): choose_printer({'composition':text},routes,'default')
        self.assertEqual(choose_printer({'composition':'(A)'},{'routes':[]},'default'),'default')

    def test_corrupt_route_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(load_routes(folder),{'enabled':False,'routes':[]})
            (Path(folder)/'printer-routes.json').write_text('{bad',encoding='utf-8')
            with self.assertRaises(PrinterRoutingError): load_routes(folder)

    def test_removing_last_assignment_does_not_fall_back_to_another_printer(self):
        with self.assertRaises(PrinterRoutingError):
            choose_printer({'composition':'(A)'},{'enabled':True,'routes':[]},'default')

if __name__=='__main__': unittest.main()
