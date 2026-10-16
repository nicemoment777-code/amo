"""Создать PDF с областью состава заказа 70 x 15 мм без перекрытия штрихкодов."""
import io
import re
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

MM = 72 / 25.4

def article_text(composition):
    values = [value.strip() for value in re.findall(r'\(([^()]*)\)', composition) if value.strip()]
    if not values:
        raise ValueError('В составе заказа нет артикулов в круглых скобках')
    return '; '.join(values)

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

def prepare_label(source, target, composition):
    composition = article_text(composition)
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
    header_width, header_height = 70 * MM, 15 * MM
    width = float(page.mediabox.width)
    height = float(page.mediabox.height) + header_height
    width_mm, height_mm = width / MM, height / MM
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
    # Extend the sheet upward; the original label stays at its original size
    # and coordinates, below the newly added 15 mm band.
    output = writer.add_blank_page(width=width, height=height)
    output.merge_page(page)
    output.merge_page(PdfReader(overlay).pages[0])
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    with open(target, 'wb') as stream:
        writer.write(stream)
    return {'widthMm':round(width_mm,4),'heightMm':round(height_mm,4),'headerMm':[70,15],'fontPt':size,'lines':len(lines),'sourceScaleX':1,'sourceScaleY':1,'layout':'top-band'}
