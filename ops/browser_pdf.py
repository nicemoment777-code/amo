"""Prepare a browser batch without sending anything to a printer."""
import json
import subprocess
import sys
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from label_pdf import prepare_label


def codes(pdf, prefix):
    subprocess.run(['pdftoppm', '-r', '203', '-singlefile', '-png', str(pdf), str(prefix)], check=True, capture_output=True, timeout=40)
    result = subprocess.run(['zbarimg', '--quiet', '--raw', str(prefix)+'.png'], capture_output=True, timeout=30)
    values = set(result.stdout.splitlines())
    if result.returncode or not values:
        raise ValueError('Не удалось проверить штрихкоды')
    return values


def main(folder):
    folder = Path(folder)
    items = json.loads((folder/'items.json').read_text(encoding='utf-8'))
    writer = PdfWriter()
    for index, item in enumerate(items):
        source, target = folder/f'{index}.pdf', folder/f'{index}-ready.pdf'
        prepare_label(source, target, item['composition'], item['deliveryService'], item.get('packageWeight'))
        if codes(source, folder/f'{index}-source') != codes(target, folder/f'{index}-output'):
            raise ValueError('Штрихкоды изменились')
        writer.add_page(PdfReader(target).pages[0])
    with (folder/'batch.pdf').open('wb') as output:
        writer.write(output)


if __name__ == '__main__':
    try:
        main(sys.argv[1])
    except Exception:
        sys.exit(1)  # No private PDF content or order fields in logs.
