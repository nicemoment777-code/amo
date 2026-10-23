"""Модель панели. Просмотр истории никогда не добавляет её в очередь печати."""
import colorsys
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from print_order import articles

MOSCOW = timezone(timedelta(hours=3))
VISIBLE_FROM = int(datetime(2026,10,1,tzinfo=MOSCOW).timestamp())
PALETTE = {
    'red': ('#ff666d', '#131936'), 'pink': ('#f99bcf', '#131936'),
    'green': ('#c1f48b', '#131936'), 'sky': ('#8bd7fa', '#131936'),
    'blue': ('#1255cf', '#ffffff'), 'black': ('#3c424e', '#ffffff'),
    'yellow': ('#ffe19a', '#131936'), 'neutral': ('#e4e8ef', '#131936'),
}

def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return default

def sku_set(item):
    try:
        return tuple(sorted(set(articles(item.get('composition', '')))))
    except ValueError:
        return ()

def order_title(item):
    number=item.get('orderNumber')
    return '№ '+str(number) if number is not None and str(number).strip() else 'amo '+str(item['id'])

def sku_color(skus):
    if not skus:
        return PALETTE['neutral']
    value = '; '.join(skus).lower()
    # Sets containing different products get their own stable colour.
    if len(skus) == 1:
        for words, name in [
            (('wsblue', 'голуб', 'sky', 'lightblue'), 'sky'),
            (('red', 'красн'), 'red'), (('pink', 'розов'), 'pink'),
            (('green', 'салат', 'зелён', 'зелен'), 'green'),
            (('blue', 'синий', 'синяя'), 'blue'),
            (('black', 'чёрн', 'черн'), 'black'),
            (('yellow', 'жёлт', 'желт'), 'yellow'),
        ]:
            if any(word in value for word in words):
                return PALETTE[name]
    hue = int.from_bytes(hashlib.sha256(value.encode()).digest()[:4], 'big') / 2**32
    rgb = colorsys.hls_to_rgb(hue, .77, .78)
    return '#' + ''.join(f'{round(channel*255):02x}' for channel in rgb), '#131936'

def print_status(item_id, state, receipts=None):
    key = str(item_id)
    if key in state.get('uncertain', {}):
        return False, 'Печать не подтверждена'
    printed = state.get('printed', {}).get(key, {})
    if printed.get('status') == 'submitted':
        return True, 'Отправлено на принтер'
    if (receipts or {}).get(key) == 'submitted':
        return True, 'Отправлено на принтер'
    if printed.get('status') == 'reserved-on-server':
        return False, 'Нет подтверждения на этом ПК'
    return False, 'Не напечатано / нет данных'

def receipt_statuses(folder):
    result = {}
    for path in Path(folder).glob('*.json'):
        if not (path.name.startswith('test-') or path.name.startswith('manual-reprint-')):
            continue
        try:
            receipt = read_json(path, {})
            records = receipt.get('items', [receipt])
            for record in records:
                if record.get('id') and record.get('status') == 'submitted':
                    result[str(record['id'])] = 'submitted'
        except (ValueError, TypeError, AttributeError):
            continue
    return result

def delivery_service(item):
    service=item.get('deliveryService')
    return service if service in ('cdek','yandex') else 'unknown'

def order_groups(items, start, end, state, receipts=None, selected_skus=None, only_unprinted=False, carrier=None):
    groups = {}
    for item in {str(v['id']): v for v in items}.values():
        if not start <= item.get('createdAt', 0) <= end:
            continue
        if carrier and delivery_service(item)!=carrier: continue
        skus = sku_set(item)
        if selected_skus is not None:
            matches=bool(set(skus).intersection(selected_skus)) if skus else None in selected_skus
            if not matches: continue
        confirmed, status = print_status(item['id'], state, receipts)
        if only_unprinted and confirmed: continue
        card = {**item, 'skus': skus, 'confirmed': confirmed, 'statusText': status}
        card['canPrint'] = bool(skus and item.get('hasLabel'))
        groups.setdefault(skus, []).append(card)
    ordered = []
    for skus, cards in sorted(groups.items(), key=lambda pair: (sku_color(pair[0])[0], pair[0])):
        ordered.append({'skus': skus, 'colors': sku_color(skus),
                        'items': sorted(cards, key=lambda v: (v.get('createdAt', 0), v['id']))})
    return ordered


def print_tab_groups(groups, confirmed):
    """Зелёная вкладка только с подтверждением; красная включает неизвестные попытки."""
    return [{**group, 'items': cards} for group in groups
            if (cards := [item for item in group['items'] if item['confirmed'] == confirmed])]

def group_by_day(groups):
    """Дни поступления по МСК, новые сверху; цвета внутри дня сохраняются."""
    days = {}
    for group in groups:
        for item in group['items']:
            day = datetime.fromtimestamp(item.get('createdAt', 0), MOSCOW).date()
            by_sku = days.setdefault(day, {})
            entry = by_sku.setdefault(group['skus'], {**group, 'day': day.strftime('%d.%m.%Y'), 'items': []})
            entry['items'].append(item)
    return [group for day in sorted(days, reverse=True) for group in days[day].values()]


def pending_by_article(groups, include_printed=False):
    """Одна заявка учитывается по каждому её артикулу, без повторов внутри артикула."""
    result={}
    for group in groups:
        for item in group['items']:
            if item['confirmed'] and not include_printed: continue
            for sku in item['skus'] or (None,):
                result.setdefault(sku,{})[str(item['id'])]=item
    return {sku:list(items.values()) for sku,items in result.items()}


def parse_period(day_from, time_from, day_to, time_to):
    try:
        start = datetime.strptime(day_from+' '+time_from, '%d.%m.%Y %H:%M').replace(tzinfo=MOSCOW)
        end = datetime.strptime(day_to+' '+time_to, '%d.%m.%Y %H:%M').replace(tzinfo=MOSCOW) + timedelta(seconds=59)
    except ValueError:
        raise ValueError('Дата: ДД.ММ.ГГГГ. Время: ЧЧ:ММ.') from None
    if end < start:
        raise ValueError('Конец периода должен быть позже начала.')
    return int(start.timestamp()), int(end.timestamp())

def merge_catalog(cached, incoming):
    values = {str(v['id']): v for v in cached}
    values.update({str(v['id']): v for v in incoming})
    return list(values.values())
