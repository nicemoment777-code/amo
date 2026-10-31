"""Общий выключатель автоматической печати для приложения и heartbeat."""
import json
import os
import math
import time
import uuid
from pathlib import Path


def auto_print_enabled(folder):
    try:
        value=json.loads((Path(folder)/'auto-print.json').read_text(encoding='utf-8'))
        return isinstance(value,dict) and value.get('enabled') is True
    except (OSError,ValueError):
        return False


def auto_print_scope(folder):
    try:
        value=json.loads((Path(folder)/'auto-print.json').read_text(encoding='utf-8'))
        start=value.get('enabledFrom'); generation=value.get('generation')
        if value.get('enabled') is True and type(start) is int and start>0 and isinstance(generation,str) and len(generation)==32:
            return start,generation
    except (OSError,ValueError,AttributeError): pass
    return None


def set_auto_print(folder, enabled, enabled_from=None):
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
    path=folder/'auto-print.json'; temp=folder/'auto-print.tmp'
    value={'enabled':bool(enabled)}
    if enabled:
        moment=time.time() if enabled_from is None else enabled_from
        if type(moment) not in (int,float) or not math.isfinite(moment) or moment<=0: raise ValueError('Некорректное время включения автопечати')
        # CRM timestamps have one-second resolution: never include the preceding second.
        value.update(enabledFrom=math.ceil(moment),generation=uuid.uuid4().hex)
    temp.write_text(json.dumps(value),encoding='utf-8')
    os.replace(temp,path)
