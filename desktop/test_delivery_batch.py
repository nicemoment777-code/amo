"""Разделение доставок проверяется без настоящего принтера и API."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_orders import FakeWorker
from print_actions import manual_batch, print_separator


class DeliveryBatchTests(unittest.TestCase):
    def run_batch(self,services,fail_separator=False,fail_order=None):
        with tempfile.TemporaryDirectory() as folder:
            worker=FakeWorker(folder); events=[]
            items=[{'id':index+1,'createdAt':index,'composition':'(A)','deliveryService':service} for index,service in enumerate(services)]
            def label(worker,key,printer,expected_service):
                events.append(key)
                self.assertEqual(expected_service,services[key-1])
                if key==fail_order: raise RuntimeError('driver failed')
                return {'widthMm':74,'heightMm':120}
            def blank(worker,details,printer):
                self.assertEqual(details,{'widthMm':74,'heightMm':120})
                events.append('blank')
                if fail_separator: raise RuntimeError('blank uncertain')
            with patch('print_actions._manual_print_locked',side_effect=label),patch('print_actions.print_separator',side_effect=blank):
                result=manual_batch(worker,items,{str(item['id']):'Test printer' for item in items},separate_delivery=True)
            batch=json.loads(next(Path(folder).glob('manual-batch-*.json')).read_text())
            return events,result,batch

    def test_cdek_then_one_blank_then_yandex_without_duplicate_order(self):
        events,result,batch=self.run_batch(['yandex','cdek','yandex','cdek'])
        self.assertEqual(events,[2,4,'blank',1,3])
        self.assertEqual(result['submitted'],['2','4','1','3'])
        self.assertEqual(batch['separator']['status'],'submitted')

    def test_single_service_does_not_feed_blank(self):
        for service in ('cdek','yandex'):
            events,_,batch=self.run_batch([service,service])
            self.assertEqual(events,[1,2]); self.assertNotIn('separator',batch)

    def test_separator_failure_stops_before_any_yandex_without_retry(self):
        events,result,batch=self.run_batch(['yandex','cdek','yandex'],fail_separator=True)
        self.assertEqual(events,[2,'blank'])
        self.assertEqual(result,{'submitted':['2'],'failed':'1','remaining':['3']})
        self.assertEqual(batch['separator']['status'],'submitting')

    def test_order_failure_stops_before_separator(self):
        events,_,batch=self.run_batch(['cdek','yandex'],fail_order=1)
        self.assertEqual(events,[1]); self.assertNotIn('separator',batch)

    def test_separator_is_white_and_uses_previous_paper_and_assigned_printer(self):
        from PIL import Image
        class Printer:
            def print_label(self,path,details,printer):
                with Image.open(path) as image:
                    self.pixels=image.getextrema()
                self.details=details; self.printer=printer; self.path=path
        worker=Printer(); details={'widthMm':74,'heightMm':120}
        print_separator(worker,details,'Assigned printer')
        self.assertEqual(worker.pixels,((255,255),)*3)
        self.assertEqual(worker.details,details); self.assertEqual(worker.printer,'Assigned printer')
        self.assertFalse(worker.path.exists())


if __name__=='__main__': unittest.main()
