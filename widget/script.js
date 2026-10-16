define(['jquery'], function ($) {
  'use strict';
  return function () {
    var self = this;
    var panel = '<div class="snowbrick-private-print"><p>Этикетки СДЭК с артикулами, масштаб 1:1.</p><p>Проверка новых заявок каждые 5 минут выполняется программой Windows. Компьютер и принтер должны быть включены.</p><p><a href="https://snowbrick.ru/integrations/amocrm" target="_blank" rel="noopener noreferrer">Подключить компьютер печати</a></p></div>';
    this.callbacks = {
      render: function () {
        if (self.system().area === 'lcard') {
          self.render_template({caption:{class_name:'snowbrick-private-print'},body:'',render:panel});
        }
        return true;
      },
      init: function () { return true; },
      bind_actions: function () { return true; },
      settings: function () {
        var root = $('.widget_settings_block__fields');
        if (root.length && !root.find('.snowbrick-private-print').length) root.append(panel);
        return true;
      },
      onSave: function () { return true; },
      destroy: function () { return true; }
    };
    return this;
  };
});
