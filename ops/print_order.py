"""Группировка этикеток по одинаковому набору артикулов."""
import re
from collections import Counter

def articles(composition):
    values = [value.strip() for value in re.findall(r'\(([^()]*)\)', composition) if value.strip()]
    if not values:
        raise ValueError('В составе заказа нет артикулов в круглых скобках')
    return values

def article_text(composition):
    return '; '.join(articles(composition))

def group_key(item):
    return tuple(sorted(set(articles(item['composition']))))

def grouped_print_order(items):
    """Число этикеток, а не число единиц товара; одна заявка — одна печать."""
    counts = Counter(group_key(item) for item in items)
    groups = {}
    for item in items:
        groups.setdefault(group_key(item), []).append(item)
    ordered = []
    for key in sorted(groups, key=lambda key: (-counts[key], min((item.get('createdAt', 0), item['id']) for item in groups[key]), key)):
        ordered.extend(sorted(groups[key], key=lambda item: (item.get('createdAt', 0), item['id'])))
    return ordered
