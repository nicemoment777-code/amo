"""Причины по сохранённым данным: без запросов, подготовки PDF и печати."""
from orders_model import sku_set, delivery_service, print_status
from printer_routing import choose_printer, PrinterRoutingError


def error_reasons(item, state, routing, default_printer, last_run=None, receipts=None, printer_names=None, offline=False):
    key = str(item['id'])
    if print_status(item['id'], state, receipts)[0]:
        return ['Отправка этой этикетки драйверу подтверждена. Физический отпечаток проверяется у принтера.']
    reasons = []
    if key in state.get('uncertain', {}):
        reasons.append('Предыдущая отправка на печать осталась без подтверждения. Проверьте отпечаток и очередь Windows. Автоматического повтора не будет.')
    elif state.get('printed', {}).get(key, {}).get('status') == 'reserved-on-server':
        reasons.append('Заявка зарезервирована на сервере, но подтверждения печати на этом компьютере нет. Проверьте другое устройство печати и очередь Windows.')
    skus = sku_set(item)
    if not skus:
        reasons.append('В поле «Состав заказа» нет артикула в круглых скобках. Заполните артикул в amoCRM и обновите карточки.')
    if not item.get('hasLabel'):
        service = delivery_service(item)
        label = {'cdek': '«Этикетка ШК СДЭК»', 'yandex': 'отдельной этикетки Яндекса'}.get(service, 'этикетки для этой службы доставки')
        reasons.append(f'Нет подходящей ссылки на PDF {label}. Проверьте поле этикетки и службу доставки в amoCRM, затем обновите карточки.')
    if skus:
        try:
            printer = choose_printer(item, routing, default_printer)
            if printer_names is not None and printer not in printer_names:
                reasons.append(f'Принтер «{printer}» не найден среди установленных принтеров Windows. Проверьте драйвер и назначения в настройках.')
        except PrinterRoutingError as error:
            reasons.append(str(error).replace('Проверьте верхнюю панель.', 'Откройте «Настройки → Принтеры и артикулы».'))
    messages = {
        'URLError': 'При последней проверке не удалось связаться с сервером. Нажмите «Проверить связь и обновить».',
        'HTTPError': 'При последней проверке сервер вернул ошибку чтения данных или этикетки. Проверьте связь и доступ к amoCRM.',
        'PrinterRoutingError': 'При последней проверке обнаружена ошибка назначения принтера. Проверьте назначения в настройках.',
        'ValueError': 'При последней проверке данные заявки или формат этикетки не прошли проверку.',
        'RuntimeError': 'При последней проверке подготовка этикетки или отправка драйверу не завершилась успешно. Точная причина в сохранённом результате не указана.',
    }
    for error in (last_run or {}).get('errors', []):
        if str(error.get('id')) == key:
            text = messages.get(error.get('type'), 'При последней проверке произошла ошибка. Подробная причина не сохранена.')
            if text not in reasons: reasons.append(text)
    if offline:
        reasons.append('Последнее обновление карточек не удалось. Здесь показаны сохранённые данные; после восстановления связи нажмите «Проверить связь и обновить».')
    if not reasons:
        reasons.append('Ошибка не зафиксирована: этикетка пока не имеет подтверждения печати на этом компьютере.')
        reasons.append('Старые заявки доступны для просмотра и ручной печати, но автоматически повторно не печатаются.')
    return reasons
