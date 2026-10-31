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
            for service, width, height, scale in [('yandex', 75, 110, 95 / 150), ('cdek', 100, 165, 1)]:
                details = prepare_label(source, target, 'Товар (test-sku)', service, '2.5 кг')
                page = PdfReader(target).pages[0]
                self.assertAlmostEqual(float(page.mediabox.width) / MM, width, places=5)
                self.assertAlmostEqual(float(page.mediabox.height) / MM, height, places=5)
                self.assertAlmostEqual(details['sourceScaleX'], scale)
                self.assertEqual(details['sourceScaleX'], details['sourceScaleY'])
                self.assertIn('test-sku', page.extract_text())
                self.assertIn('2,5 кг',page.extract_text())
                self.assertGreaterEqual(details['fontPt'],12)
                self.assertTrue(any('Bold' in str(font.get_object().get('/BaseFont')) for font in page['/Resources']['/Font'].values()))
                with self.assertRaises(ValueError): prepare_label(source,target,'(test-sku)',service)

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
