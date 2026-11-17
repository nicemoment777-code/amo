"""Группировка этикеток по одинаковому набору артикулов."""
import re
from collections import Counter

def articles(composition):
    values = [value.strip() for value in re.findall(r'\(([^()]*)\)', composition) if value.strip()]
    if not values:
        raise ValueError('В составе заказа нет артикулов в круглых скобках')
    return values

def product_count(composition):
    """Количество строк товара умножается на число элементов в артикуле."""
    matches=list(re.finditer(r'\(([^()]*)\)',composition))
    if not matches or any(not m[1].strip() for m in matches):
        raise ValueError('В составе заказа нет артикулов')
    count=0
    for index,match in enumerate(matches):
        sku=match[1].strip()
        tail=composition[match.end():matches[index+1].start() if index+1<len(matches) else len(composition)]
        # Quantity must immediately follow this SKU; prices, years and names are not counts.
        quantity=re.match(r'\s*,?\s*(?:шт\.?\s*)?[-:—–]\s*(\d+)(?=\s*(?:[xх×*]|шт|[,;\n]|$))',tail,re.I)
        amount=int(quantity[1]) if quantity else 1
        if not 1<=amount<=10000: raise ValueError('Некорректное количество товара')
        count+=amount*(2 if re.match(r'^2[_-]',sku) else 1)
    return count


def article_text(composition):
    return '; '.join(articles(composition))

def printable_article_text(composition):
    """Скрываем год только в печатной надписи; исходные SKU не меняем."""
    values=[re.sub(r'[_\-\s]*2027$', '',sku).strip() for sku in articles(composition)]
    if any(not value for value in values):
        raise ValueError('После скрытия года в артикуле не осталось текста')
    return '; '.join(values)


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
