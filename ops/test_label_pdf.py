import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'data' / 'printing' / 'vendor'))
from pypdf import PdfWriter, PdfReader
from label_pdf import MM, prepare_label


class LabelSizeTest(unittest.TestCase):
    def test_carrier_sizes_and_uniform_scale(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / 'source.pdf', Path(folder) / 'out.pdf'
            writer = PdfWriter()
            writer.add_blank_page(width=100 * MM, height=150 * MM)
            writer.write(source)
            for service, width, height, scale in [('yandex', 75, 115, 95 / 150), ('cdek', 100, 170, 1)]:
                details = prepare_label(source, target, 'Товар (test-sku)', service, '2.5 кг')
                page = PdfReader(target).pages[0]
                self.assertAlmostEqual(float(page.mediabox.width) / MM, width, places=5)
                self.assertAlmostEqual(float(page.mediabox.height) / MM, height, places=5)
                self.assertAlmostEqual(details['sourceScaleX'], scale)
                self.assertEqual(details['sourceScaleX'], details['sourceScaleY'])
                self.assertIn('test-sku', page.extract_text())
                self.assertIn('2,5 кг',page.extract_text())
                self.assertGreaterEqual(details['fontPt'],10)
                self.assertTrue(any('Bold' in str(font.get_object().get('/BaseFont')) for font in page['/Resources']['/Font'].values()))
                details=prepare_label(source,target,'(test-sku)',service)
                self.assertFalse(details['weightIncluded'])
                self.assertIn('test-sku',PdfReader(target).pages[0].extract_text())

    def test_unknown_or_ambiguous_weight_never_blocks_sku_header(self):
        with tempfile.TemporaryDirectory() as folder:
            source,target=Path(folder)/'source.pdf',Path(folder)/'out.pdf'
            writer=PdfWriter();writer.add_blank_page(width=75*MM,height=95*MM);writer.write(source)
            for weight in [None,'unknown','-1 кг','2 кг; 3 кг']:
                details=prepare_label(source,target,'(SKU_REQUIRED)','yandex',weight)
                self.assertFalse(details['weightIncluded']);self.assertIn('SKU_REQUIRED',''.join(PdfReader(target).pages[0].extract_text().split()))
            with self.assertRaises(ValueError):prepare_label(source,target,'Товар без артикула','yandex')

    def test_sku_takes_priority_when_weight_does_not_fit_in_the_header(self):
        with tempfile.TemporaryDirectory() as folder:
            source,target=Path(folder)/'source.pdf',Path(folder)/'out.pdf'
            writer=PdfWriter();writer.add_blank_page(width=75*MM,height=95*MM);writer.write(source)
            sku='A'*42
            details=prepare_label(source,target,'('+sku+')','yandex','10000 кг')
            self.assertIn(sku,''.join(PdfReader(target).pages[0].extract_text().split()))
            self.assertGreaterEqual(details['fontPt'],10)

    def test_long_sku_sets_shrink_below_twelve_without_changing_band(self):
        with tempfile.TemporaryDirectory() as folder:
            source,target=Path(folder)/'source.pdf',Path(folder)/'out.pdf'
            writer=PdfWriter();writer.add_blank_page(width=75*MM,height=95*MM);writer.write(source)
            skus=['SKU_'+str(i)+'_'+'A'*35 for i in range(5)]
            for service in ['cdek','yandex']:
                details=prepare_label(source,target,'; '.join('('+sku+')' for sku in skus),service)
                self.assertLess(details['fontPt'],12)
                self.assertGreater(details['fontPt'],0)
                self.assertEqual(details['headerMm'],[70,20])
                self.assertAlmostEqual(details['heightMm'],115,places=3)
                self.assertAlmostEqual(float(PdfReader(target).pages[0].mediabox.height)/MM,115,places=3)
                text=''.join(PdfReader(target).pages[0].extract_text().split())
                for sku in skus:self.assertIn(sku,text)

    def test_count_uses_each_article_and_double_prefix_only(self):
        from print_order import product_count
        for composition,count in [('(A_2027)',1),('(2_Red-Blue_2027)',2),('(A); (2_B-C)',3),('(2_A-B); (2_C-D)',4),('(A); (A)',2),('(12_blue_2027)',1)]:
            with self.subTest(count=count,composition=composition), tempfile.TemporaryDirectory() as folder:
                self.assertEqual(product_count(composition),count)
                source,target=Path(folder)/'source.pdf',Path(folder)/'out.pdf'
                writer=PdfWriter();writer.add_blank_page(width=75*MM,height=95*MM);writer.write(source)
                result=prepare_label(source,target,composition,'yandex')
                self.assertEqual(result['productCount'],count)
                self.assertEqual(PdfReader(target).pages[0].extract_text().splitlines()[0],str(count))
                self.assertGreater(result['countFontPt'],40)
                self.assertEqual(result['headerMm'],[70,20])
                self.assertEqual(result['headerContentTopMm'],5)
                self.assertEqual(result['headerContentHeightMm'],15)
                self.assertEqual(result['countFontScale'],0.75)
                self.assertNotIn('2027',PdfReader(target).pages[0].extract_text())

    def test_landscape_fits_width_below_header(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / 'source.pdf', Path(folder) / 'out.pdf'
            writer = PdfWriter()
            writer.add_blank_page(width=200 * MM, height=100 * MM)
            writer.write(source)
            details = prepare_label(source, target, '(test-sku)', 'yandex', '2500 г')
            self.assertAlmostEqual(details['sourceScaleX'], 75 / 200)


if __name__ == '__main__':
    unittest.main()
