import io
from pathlib import Path
import tempfile
import unittest
from urllib.error import URLError
from pypdf import PdfWriter
from pdf_archive import archive_labels,save_pdf


def pdf(width=74):
    out=io.BytesIO(); writer=PdfWriter(); writer.add_blank_page(width=width,height=105); writer.write(out); return out.getvalue()


class ArchiveTests(unittest.TestCase):
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
