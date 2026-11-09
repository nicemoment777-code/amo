import json
import tempfile
from pathlib import Path
from reportlab.pdfgen import canvas
from reportlab.graphics.barcode import code128
from pypdf import PdfReader
from browser_pdf import main

with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    c = canvas.Canvas(str(folder/'0.pdf'), pagesize=(75*72/25.4, 95*72/25.4))
    code128.Code128('123456789012', barHeight=40, barWidth=1).drawOn(c,20,60)
    c.save()
    (folder/'items.json').write_text(json.dumps([{'composition':'Товар (TEST_BLUE)', 'deliveryService':'yandex', 'packageWeight':'2 кг'}]), encoding='utf-8')
    main(folder)
    output=PdfReader(folder/'batch.pdf')
    assert len(output.pages)==1
    assert abs(float(output.pages[0].mediabox.height)-115*72/25.4)<.01
    assert 'TEST_BLUE' in output.pages[0].extract_text()
    print('BROWSER_PDF_SELF_TEST_OK')
