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
                details = prepare_label(source, target, 'Товар (test-sku)', service)
                page = PdfReader(target).pages[0]
                self.assertAlmostEqual(float(page.mediabox.width) / MM, width, places=5)
                self.assertAlmostEqual(float(page.mediabox.height) / MM, height, places=5)
                self.assertAlmostEqual(details['sourceScaleX'], scale)
                self.assertEqual(details['sourceScaleX'], details['sourceScaleY'])
                self.assertIn('test-sku', page.extract_text())

    def test_landscape_fits_width_below_header(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / 'source.pdf', Path(folder) / 'out.pdf'
            writer = PdfWriter()
            writer.add_blank_page(width=200 * MM, height=100 * MM)
            writer.write(source)
            details = prepare_label(source, target, '(test-sku)', 'yandex')
            self.assertAlmostEqual(details['sourceScaleX'], 75 / 200)


if __name__ == '__main__':
    unittest.main()
