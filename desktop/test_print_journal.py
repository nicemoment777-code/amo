import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'ops'))
from print_journal import append_entry,read_entries


class JournalTests(unittest.TestCase):
    def test_reprints_survive_restart_as_separate_copies_without_receipt_duplicates(self):
        with tempfile.TemporaryDirectory() as folder:
            item={'id':1,'orderNumber':'0007','composition':'Товар (A); Товар (B)'}
            self.assertTrue(append_entry(folder,item,'P','manual','manual-reprint-1-a.json'))
            self.assertTrue(append_entry(folder,item,'P','manual','manual-reprint-1-b.json'))
            for suffix in ('a','b'):
                (Path(folder)/f'manual-reprint-1-{suffix}.json').write_text(json.dumps({'id':1,'at':1,'status':'submitted'}))
            (Path(folder)/'state.json').write_text(json.dumps({'printed':{'1':{'at':1,'status':'submitted'}}}))
            first=read_entries(folder); second=read_entries(folder)
            self.assertEqual(len(first),2); self.assertEqual(first,second)
            self.assertEqual(first[0]['orderNumber'],'0007'); self.assertEqual(first[0]['skus'],['A','B'])

    def test_old_state_and_receipts_are_visible_and_uncertain_is_not_counted_as_success(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder)/'manual-reprint-1-old.json').write_text(json.dumps({'id':1,'at':1,'status':'submitted','printer':'P'}))
            (Path(folder)/'state.json').write_text(json.dumps({'printed':{'1':{'at':1,'status':'submitted'},'2':{'at':2,'status':'submitted'},'3':{'at':3,'status':'reserved-on-server'}},'uncertain':{'4':{'at':4}}}))
            entries=read_entries(folder)
            self.assertEqual(len(entries),3)
            self.assertEqual(sum(v.get('status')=='submitted' for v in entries),2)
            self.assertEqual(entries[0]['status'],'uncertain')

    def test_journal_disk_failure_does_not_trigger_print_retry(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(Path,'write_text',side_effect=OSError('disk full')):
            self.assertFalse(append_entry(folder,{'id':1},'P','auto'))

    def test_legacy_test_confirmations_import_without_reprinting_or_inventing_time(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'test-old.json').write_text(json.dumps({'id':9,'status':'submitted'}))
            (root/'test-batch-grouped.json').write_text(json.dumps({'at':10,'items':[{'id':9,'status':'submitted'},{'id':10,'status':'submitted'},{'id':11,'status':'prepared'}]}))
            values=read_entries(root)
            self.assertEqual({v['id'] for v in values},{'9','10'})
            self.assertEqual(len(values),2)
