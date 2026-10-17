"""Один артикул закрепляется только за одним принтером Windows."""
import json
from pathlib import Path
from print_order import group_key

class PrinterRoutingError(ValueError):
    pass

def normalize_routes(config):
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
