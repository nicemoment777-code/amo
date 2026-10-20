import io
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'ops'))
from urllib.error import URLError
from pypdf import PdfWriter
from pdf_archive import archive_labels,save_pdf,load_pdf


def pdf(width=74):
    out=io.BytesIO(); writer=PdfWriter(); writer.add_blank_page(width=width,height=105); writer.write(out); return out.getvalue()


class ArchiveTests(unittest.TestCase):
    def test_printing_repairs_damaged_archive_with_same_original_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            item={'id':1,'deliveryService':'cdek'}; content=pdf()
            path=save_pdf(root,item,content); path.write_bytes(b'broken')
            self.assertEqual(load_pdf(root,item,lambda _:content),content)
            self.assertEqual(path.read_bytes(),content)
            self.assertEqual(load_pdf(root,item,lambda _:self.fail('Repaired cache must be reused')),content)
    def test_printing_prefers_local_pdf_without_downloading_again(self):
        with tempfile.TemporaryDirectory() as root:
            item={'id':1,'deliveryService':'cdek'}; content=pdf()
            save_pdf(root,item,content)
            self.assertEqual(load_pdf(root,item,lambda _:self.fail('Local PDF must be used')),content)

    def test_printing_downloads_missing_pdf_and_saves_for_next_print(self):
        with tempfile.TemporaryDirectory() as root:
            item={'id':2,'deliveryService':'yandex'}; content=pdf(); calls=[]
            self.assertEqual(load_pdf(root,item,lambda path:calls.append(path) or content),content)
            self.assertEqual(calls,['label/2'])
            self.assertEqual(load_pdf(root,item,lambda _:self.fail('Already archived')),content)
            self.assertEqual(len(list((Path(root)/'Яндекс').glob('*.pdf'))),1)

    def test_printing_rejects_changed_cached_bytes_and_never_uses_other_carrier(self):
        with tempfile.TemporaryDirectory() as root:
            item={'id':1,'deliveryService':'cdek'}
            damaged=save_pdf(root,item,pdf()); damaged.write_bytes(b'%PDF-broken')
            wrong=save_pdf(root,{'id':1,'deliveryService':'yandex'},pdf(90))
            calls=[]; content=pdf(80)
            self.assertEqual(load_pdf(root,item,lambda path:calls.append(path) or content),content)
            self.assertEqual(calls,['label/1']); self.assertTrue(wrong.exists())
            self.assertEqual(damaged.read_bytes(),b'%PDF-broken')

    def test_archive_routes_originals_and_restarts_without_redownloading(self):
        with tempfile.TemporaryDirectory() as root:
            items=[{'id':1,'hasLabel':True,'deliveryService':'cdek'}, {'id':2,'hasLabel':True,'deliveryService':'yandex'},
                   {'id':3,'hasLabel':False,'deliveryService':'yandex'}, {'id':4,'hasLabel':True,'deliveryService':'unknown'}]
            calls=[]; content=pdf()
            result=archive_labels(root,items,lambda path:calls.append(path) or content)
            self.assertEqual(result,{'saved':2,'existing':0,'waiting':2,'errors':0})
            self.assertEqual(next((Path(root)/'СДЭК').glob('*.pdf')).read_bytes(),content)
            self.assertEqual(len(list((Path(root)/'Яндекс').glob('*.pdf'))),1)
            result=archive_labels(root,items,lambda _:self.fail('Already archived'))
            self.assertEqual(result['existing'],2)
            self.assertEqual(len(calls),2)

    def test_invalid_pdf_never_becomes_final_file_and_retries_later(self):
        with tempfile.TemporaryDirectory() as root:
            items=[{'id':1,'hasLabel':True,'deliveryService':'cdek'}]
            self.assertEqual(archive_labels(root,items,lambda _:b'html error')['errors'],1)
            self.assertFalse(list(Path(root).rglob('*.pdf')))
            self.assertEqual(archive_labels(root,items,lambda _:pdf())['saved'],1)
            self.assertFalse(list(Path(root).rglob('*.tmp')))

    def test_versions_are_preserved_and_ids_cannot_escape_archive(self):
        with tempfile.TemporaryDirectory() as root:
            item={'id':1,'deliveryService':'cdek'}
            first=save_pdf(root,item,pdf()); second=save_pdf(root,item,pdf(80))
            self.assertNotEqual(first,second); self.assertTrue(first.exists())
            with self.assertRaises(ValueError): save_pdf(root,{'id':'../outside','deliveryService':'cdek'},pdf())

    def test_network_failure_keeps_archive_and_stops_requests_until_next_pass(self):
        with tempfile.TemporaryDirectory() as root:
            items=[{'id':n,'hasLabel':True,'deliveryService':'cdek'} for n in (1,2)]
            calls=[]
            def fail(path): calls.append(path); raise URLError('offline')
            self.assertEqual(archive_labels(root,items,fail)['errors'],1)
            self.assertEqual(len(calls),1)
            self.assertEqual(archive_labels(root,items,lambda _:pdf())['saved'],2)


if __name__=='__main__': unittest.main()
