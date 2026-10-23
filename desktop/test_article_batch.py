"""Whole carrier batches: preflight, unique SKU sets and separator failures."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_orders import FakeWorker
from print_actions import manual_batch
from orders_model import order_groups, pending_by_article


class ArticleBatchTests(unittest.TestCase):
    def run_batch(self, fail_blank=False, invalid=False):
        with tempfile.TemporaryDirectory() as folder:
            worker=FakeWorker(folder); events=[]
            items=[{'id':i,'createdAt':i,'hasLabel':True,'composition':sku,'deliveryService':'yandex'}
                   for i,sku in [(1,'(A)'),(2,'(B)'),(3,'(A)'),(4,'(C); (D)')]]
            def request(path,body=None):
                item=dict(next(v for v in items if str(v['id'])==path.split('/')[1]))
                if invalid and item['id']==4: item['composition']='(CHANGED)'
                return json.dumps(item).encode()
            worker.request=request
            def label(worker,key,printer,service,skus):
                events.append(key)
                return {'widthMm':75,'heightMm':110}
            def blank(worker,details,printer):
                events.append(('blank',printer))
                if fail_blank: raise RuntimeError('blank uncertain')
            printers={'1':'Test printer','2':'Other printer','3':'Test printer','4':'Test printer'}
            worker.select_printer=lambda v:printers[str(v['id'])]
            with patch('print_actions._manual_print_locked',side_effect=label),patch('print_actions.print_separator',side_effect=blank):
                if invalid:
                    with self.assertRaises(ValueError): manual_batch(worker,items,printers,separate_articles=True)
                    self.assertEqual(events,[]); return
                result=manual_batch(worker,items+[items[0]],printers,separate_articles=True)
            batch=json.loads(next(Path(folder).glob('manual-batch-*.json')).read_text())
            return events,result,batch

    def test_groups_multi_sku_once_with_blanks_on_finished_group_printer(self):
        events,result,batch=self.run_batch()
        self.assertEqual(events,[1,3,('blank','Test printer'),2,('blank','Other printer'),4])
        self.assertEqual(result['submitted'],['1','3','2','4'])
        self.assertEqual(len(batch['separators']),2)

    def test_uncertain_blank_stops_batch_without_following_order(self):
        events,result,batch=self.run_batch(fail_blank=True)
        self.assertEqual(events,[1,3,('blank','Test printer')])
        self.assertEqual(result['failed'],'2')
        self.assertEqual(batch['separators'][0]['status'],'submitting')

    def test_changed_last_item_prevents_entire_batch(self): self.run_batch(invalid=True)

    def test_carrier_article_counts_include_printed_and_dedupe_multi_sku(self):
        items=[{'id':1,'createdAt':1,'composition':'(A); (A); (B)','hasLabel':True,'deliveryService':'yandex'},
               {'id':2,'createdAt':1,'composition':'(A)','hasLabel':True,'deliveryService':'cdek'}]
        groups=order_groups(items,0,2,{'printed':{'1':{'status':'submitted'}}},carrier='yandex')
        self.assertEqual(pending_by_article(groups),{})
        counts=pending_by_article(groups,include_printed=True)
        self.assertEqual({k:len(v) for k,v in counts.items()},{'A':1,'B':1})


if __name__=='__main__': unittest.main()
