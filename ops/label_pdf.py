"""Создать PDF с областью состава заказа 70 x 15 мм без перекрытия штрихкодов."""
import io
from pathlib import Path
from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

MM = 72 / 25.4

def wrap(text, font, size, width):
    lines = []
    line = ''
    for word in text.split():
        candidate = (line + ' ' + word).strip()
        if pdfmetrics.stringWidth(candidate, font, size) <= width:
            line = candidate
            continue
        if line:
            lines.append(line)
        line = ''
        for char in word:
            if pdfmetrics.stringWidth(line + char, font, size) > width:
                lines.append(line)
                line = ''
            line += char
    if line:
        lines.append(line)
    return lines

def prepare_label(source, target, composition, width_mm=78.74, height_mm=101.6):
    font = 'LabelArial'
    if font not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(font, 'C:/Windows/Fonts/arial.ttf'))
    if not composition.strip() or len(composition) > 10000:
        raise ValueError('Некорректный состав заказа')
    reader = PdfReader(source)
    if len(reader.pages) != 1:
        raise ValueError('Автоматическая печать поддерживает только одностраничные этикетки')
    page = reader.pages[0]
    page.transfer_rotation_to_content()
    width, height = width_mm * MM, height_mm * MM
    header_width, header_height = 70 * MM, 15 * MM
    if width_mm < 72 or height_mm < 50:
        raise ValueError('Недостаточный размер бумаги')
    x = (width - header_width) / 2
    available_width = header_width - 2 * MM
    for size in [10, 9, 8, 7, 6]:
        lines = wrap(composition, font, size, available_width)
        leading = size * 1.15
        if len(lines) * leading <= header_height - 2 * MM:
            break
    else:
        raise ValueError('Состав заказа не помещается в 70 x 15 мм с читаемым шрифтом')
    overlay = io.BytesIO()
    c = canvas.Canvas(overlay, pagesize=(width, height))
    c.setFont(font, size)
    # Physical header is at the top, with a 1 mm internal text inset.
    y = height - (header_height - len(lines)*leading)/2 - size
    for line in lines:
        c.drawString(x + MM, y, line)
        y -= leading
    c.save()
    writer = PdfWriter()
    output = writer.add_blank_page(width=width, height=height)
    original_width, original_height = float(page.mediabox.width), float(page.mediabox.height)
    scale_x = min(1, (width - 2*MM)/original_width)
    scale_y = min(scale_x, (height-header_height-2*MM)/original_height)
    # Keep horizontal barcode module widths. Reducing both axes made this CDEK
    # label unreadable at 203 dpi; only the vertical layout is compressed.
    output.merge_transformed_page(page, Transformation().translate(-float(page.mediabox.left), -float(page.mediabox.bottom)).scale(scale_x, scale_y).translate((width-original_width*scale_x)/2, MM))
    output.merge_page(PdfReader(overlay).pages[0])
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    with open(target, 'wb') as stream:
        writer.write(stream)
    return {'widthMm':width_mm,'heightMm':height_mm,'headerMm':[70,15],'fontPt':size,'lines':len(lines),'sourceScaleX':round(scale_x,4),'sourceScaleY':round(scale_y,4)}
