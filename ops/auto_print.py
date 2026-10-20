"""Общий выключатель автоматической печати для приложения и heartbeat."""
import json
import os
from pathlib import Path


def auto_print_enabled(folder):
    try:
        value=json.loads((Path(folder)/'auto-print.json').read_text(encoding='utf-8'))
        return isinstance(value,dict) and value.get('enabled') is True
    except (OSError,ValueError):
        return False


def set_auto_print(folder, enabled):
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
    path=folder/'auto-print.json'; temp=folder/'auto-print.tmp'
    temp.write_text(json.dumps({'enabled':bool(enabled)}),encoding='utf-8')
    os.replace(temp,path)
