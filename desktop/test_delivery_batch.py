"""Партии доставок идут подряд без пустых стикеров, без настоящего принтера."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_orders import FakeWorker
from print_actions import manual_batch


class DeliveryBatchTests(unittest.TestCase):
    def run_batch(self,services,fail_order=None):
        with tempfile.TemporaryDirectory() as folder:
            worker=FakeWorker(folder); events=[]
            items=[{'id':index+1,'createdAt':index,'composition':'(A)','deliveryService':service} for index,service in enumerate(services)]
            def label(worker,key,printer,expected_service):
                events.append(key)
                self.assertEqual(expected_service,services[key-1])
                if key==fail_order: raise RuntimeError('driver failed')
                return {'widthMm':74,'heightMm':120}
            worker.print_label=lambda *_:self.fail('Unexpected extra label')
            printers={str(v['id']):'Printer '+v['deliveryService'] for v in items}
            with patch('print_actions._manual_print_locked',side_effect=label):
                result=manual_batch(worker,items,printers,separate_delivery=True)
            batch=json.loads(next(Path(folder).glob('manual-batch-*.json')).read_text())
            self.assertNotIn('separator',batch); self.assertNotIn('separators',batch)
            return events,result,batch

    def test_mixed_services_print_consecutively_on_assigned_printers(self):
        events,result,_=self.run_batch(['yandex','cdek','yandex','cdek'])
        self.assertEqual(events,[2,4,1,3])
        self.assertEqual(result['submitted'],['2','4','1','3'])

    def test_single_service_has_no_extra_label(self):
        for service in ('cdek','yandex'):
            events,_,_=self.run_batch([service,service])
            self.assertEqual(events,[1,2])

    def test_real_order_failure_stops_without_retry(self):
        events,result,_=self.run_batch(['yandex','cdek','yandex'],fail_order=1)
        self.assertEqual(events,[2,1])
        self.assertEqual(result,{'submitted':['2'],'failed':'1','remaining':['3']})


if __name__=='__main__': unittest.main()
