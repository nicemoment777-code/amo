"""Один артикул закрепляется только за одним принтером Windows."""
import json
from pathlib import Path
from print_order import group_key

class PrinterRoutingError(ValueError):
    pass

def normalize_routes(config):
    if isinstance(config,dict) and 'slots' in config:
        if not isinstance(config['slots'],list): raise PrinterRoutingError('Некорректные строки принтеров')
        slots=[]; selected_printers=set()
        for slot in config['slots']:
            if not isinstance(slot,dict): raise PrinterRoutingError('Некорректная строка принтера')
            printer=slot.get('printer',''); skus=slot.get('skus',[])
            if not isinstance(printer,str) or not isinstance(skus,list) or any(not isinstance(s,str) or not s.strip() for s in skus):
                raise PrinterRoutingError('Некорректные артикулы принтера')
            printer=printer.strip(); skus=sorted(set(s.strip() for s in skus))
            if not printer and skus: raise PrinterRoutingError('Для артикулов не выбран принтер')
            if printer and printer in selected_printers: raise PrinterRoutingError('Принтер уже выбран в другой строке')
            if printer: selected_printers.add(printer)
            slots.append({'printer':printer,'skus':skus})
        derived=[slot for slot in slots if slot['printer'] and slot['skus']]
        result=normalize_routes({'enabled':config.get('enabled',bool(derived)),'routes':derived})
        if 'routes' in config and normalize_routes({'routes':config['routes']})['routes']!=result['routes']:
            raise PrinterRoutingError('Назначения не совпадают со строками принтеров')
        return {**result,'slots':slots}
    if not isinstance(config,dict) or not isinstance(config.get('routes',[]),list):
        raise PrinterRoutingError('Повреждены назначения принтеров. Проверьте верхнюю панель.')
    owners={}; routes=[]; printers=set()
    for route in config.get('routes',[]):
        if not isinstance(route,dict): raise PrinterRoutingError('Некорректное назначение принтера')
        printer=route.get('printer','')
        skus=route.get('skus',[])
        if not isinstance(printer,str) or not printer.strip() or not isinstance(skus,list) or any(not isinstance(s,str) or not s.strip() for s in skus):
            raise PrinterRoutingError('Выберите принтер и артикулы')
        printer=printer.strip(); skus=sorted(set(s.strip() for s in skus))
        if not skus: raise PrinterRoutingError('Выберите хотя бы один артикул')
        if printer in printers: raise PrinterRoutingError('Принтер уже есть в списке назначений')
        printers.add(printer)
        for sku in skus:
            if sku in owners: raise PrinterRoutingError('Один артикул нельзя назначить нескольким принтерам')
            owners[sku]=printer
        routes.append({'printer':printer,'skus':skus})
    enabled=config.get('enabled',bool(routes))
    if not isinstance(enabled,bool): raise PrinterRoutingError('Некорректный режим назначений принтеров')
    return {'enabled':enabled,'routes':routes}

def load_routes(folder):
    path=Path(folder)/'printer-routes.json'
    try: return normalize_routes(json.loads(path.read_text(encoding='utf-8')))
    except FileNotFoundError: return {'enabled':False,'routes':[]}
    except json.JSONDecodeError: raise PrinterRoutingError('Не удалось прочитать назначения принтеров') from None

def choose_printer(item, config, default):
    config=normalize_routes(config)
    if not config['enabled']: return default
    owners={sku:route['printer'] for route in config['routes'] for sku in route['skus']}
    skus=group_key(item)
    if any(sku not in owners for sku in skus):
        raise PrinterRoutingError('Для артикула не назначен принтер. Проверьте верхнюю панель.')
    selected={owners[sku] for sku in skus}
    if len(selected)!=1:
        raise PrinterRoutingError('Артикулы одной заявки назначены разным принтерам. Перенесите их на один принтер.')
    return selected.pop()
