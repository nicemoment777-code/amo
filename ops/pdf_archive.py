"""Постоянный архив исходных PDF, независимый от очереди печати."""
import ctypes
import hashlib
import io
import os
from pathlib import Path
import tempfile
from urllib.error import HTTPError, URLError


FOLDERS={'cdek':'СДЭК','yandex':'Яндекс'}


def archive_directory():
    # Системный путь учитывает перенос рабочего стола, в том числе в OneDrive.
    desktop=ctypes.create_unicode_buffer(32768)
    result=ctypes.windll.shell32.SHGetFolderPathW(None,0x10,None,0,desktop)
    if result or not desktop.value:
        raise OSError('Не удалось определить папку рабочего стола')
    return Path(desktop.value)/'Этикетки доставка'


def validate_pdf(content):
    from pypdf import PdfReader
    if len(content)>10_000_000 or not content.startswith(b'%PDF-'):
        raise ValueError('Получен некорректный PDF')
    reader=PdfReader(io.BytesIO(content))
    if reader.is_encrypted or not len(reader.pages): raise ValueError('PDF не читается')


def load_pdf(root,item,download):
    """Сначала проверенный исходник нужной доставки; иначе загрузка и архивирование."""
    service=item.get('deliveryService'); key=str(item['id'])
    if service not in FOLDERS: raise ValueError('Не определена служба доставки')
    if not key.isascii() or not key.isdigit(): raise ValueError('Некорректный ID заявки')
    folder=Path(root)/FOLDERS[service]
    candidates=sorted(folder.glob(key+'-*.pdf'),key=lambda path:path.stat().st_mtime_ns,reverse=True)
    for path in candidates:
        try:
            if path.stat().st_size>10_000_000: continue
            content=path.read_bytes()
            expected=key+'-'+hashlib.sha256(content).hexdigest()[:16]+'.pdf'
            if path.name!=expected: continue
            validate_pdf(content)
            return content
        except Exception:
            continue
    content=download('label/'+key)
    save_pdf(root,item,content)
    return content


def save_pdf(root,item,content):
    service=item.get('deliveryService')
    if service not in FOLDERS: raise ValueError('Не определена служба доставки')
    key=str(item['id'])
    if not key.isascii() or not key.isdigit(): raise ValueError('Некорректный ID заявки')
    validate_pdf(content)
    folder=Path(root)/FOLDERS[service]; folder.mkdir(parents=True,exist_ok=True)
    target=folder/(key+'-'+hashlib.sha256(content).hexdigest()[:16]+'.pdf')
    if target.exists() and target.read_bytes()==content: return target
    temp=None
    try:
        with tempfile.NamedTemporaryFile(dir=folder,prefix='.',suffix='.tmp',delete=False) as output:
            temp=Path(output.name); output.write(content); output.flush(); os.fsync(output.fileno())
        os.replace(temp,target)
    finally:
        if temp is not None: temp.unlink(missing_ok=True)
    return target


def archive_labels(root,items,download,stopped=lambda:False,progress=lambda result:None):
    root=Path(root)
    for name in FOLDERS.values(): (root/name).mkdir(parents=True,exist_ok=True)
    result={'saved':0,'existing':0,'waiting':0,'errors':0}
    unique={str(item['id']):item for item in items}
    for key,item in sorted(unique.items(),key=lambda pair:pair[1].get('createdAt',0),reverse=True):
        if stopped(): break
        service=item.get('deliveryService')
        if not item.get('hasLabel') or service not in FOLDERS:
            result['waiting']+=1; continue
        if not key.isascii() or not key.isdigit():
            result['errors']+=1; continue
        if any((root/FOLDERS[service]).glob(key+'-*.pdf')):
            result['existing']+=1; continue
        try:
            save_pdf(root,item,download('label/'+key)); result['saved']+=1
        except HTTPError as error:
            result['errors']+=1
            if error.code>=500:
                progress(dict(result)); break
        except URLError:
            result['errors']+=1; progress(dict(result)); break
        except (OSError,ValueError):
            result['errors']+=1
        except Exception:
            result['errors']+=1
        progress(dict(result))
    progress(dict(result))
    return result
