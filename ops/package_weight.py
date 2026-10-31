"""Только явно подписанный вес, без расчёта по артикулам или числу мест."""
from decimal import Decimal,InvalidOperation
import re


def kilograms(value,default_unit=None):
    match=re.fullmatch(r'\s*(\d+(?:[.,]\d+)?)\s*(кг|kg|г|g)?\s*',str(value),re.I)
    if not match: raise ValueError('Некорректный итоговый вес посылки')
    unit=(match[2] or default_unit or '').lower()
    if unit not in ('кг','kg','г','g'): raise ValueError('Не указана единица веса посылки')
    number=Decimal(match[1].replace(',','.'))
    if unit in ('г','g'): number/=1000
    if number<=0 or number>10000: raise ValueError('Некорректный итоговый вес посылки')
    return format(number.normalize(),'f').replace('.',',')+' кг'


def label_weight(text):
    # Explicit total takes precedence; distinct parcel weights are never summed.
    total=r'(?:итоговый|общий)\s+вес'
    for prefix in (total,r'(?<![а-я])вес'):
        prefix_values=re.findall(prefix+r'\s*[:,]?\s*(кг|kg|г|g)\s*[:]?\s*(\d+(?:[.,]\d+)?)',text,re.I)
        suffix_values=re.findall(prefix+r'\s*[:,]?\s*(\d+(?:[.,]\d+)?)\s*(кг|kg|г|g)\b',text,re.I)
        values={kilograms(number,unit) for unit,number in prefix_values}
        values.update(kilograms(number,unit) for number,unit in suffix_values)
        if values:
            if len(values)!=1: raise ValueError('В этикетке несколько разных значений веса')
            return values.pop()
    raise ValueError('В заявке и исходной этикетке не найден итоговый вес посылки')
