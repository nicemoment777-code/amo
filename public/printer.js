import {day,stamp,title,filterItems,articleCounts,orderedGroups} from '/printer-model.js';
const $=id=>document.getElementById(id);
const printerIcon='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M6 9V3h12v6M6 17H3V9h18v8h-3M6 14h12v7H6z"/><path d="M17 11h2"/></svg>';
const copyIcon='<svg viewBox="0 0 20 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M5 6V2h12v16h-3M2 6h12v16H2z"/></svg>';
let snapshot=null,devices=[],device=localStorage.getItem('snowbrick-device')||'',carrier='all',status='pending',query='',selected=new Set(),skuFilter=null,selection=false,range=null,busy=false,plan=null,hydratedDevice='',routesDraft=[];
let visible=[],deliveryItems=[],allPeriod=[],cloud=null,cloudAt=0,cloudFrom=null,verified=false;
const online=()=>devices.find(v=>v.id===device)?.online===true;
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function notice(text,error=false){$('notice').textContent=text;$('notice').classList.toggle('error',error);$('settingsNotice').textContent=text;$('settingsNotice').classList.toggle('error',error);}
async function api(path,body){const r=await fetch('/api/browser/'+path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});if(r.status===401){location.assign('/login');throw Error('Войдите на сайт');}const d=await r.json();if(!r.ok)throw Error(d.error||'Не удалось выполнить действие');return d;}
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function command(action,args={}){
  if(busy)throw Error('Дождитесь завершения текущего действия');
  if(!online())throw Error('Выберите подключённый компьютер печати');
  busy=true;renderDisabled();notice(action==='plan'?'Проверяем партию перед подтверждением…':action==='print'?'Готовим и проверяем все этикетки. Затем отправляем на принтер…':'Выполняем действие на выбранном компьютере…');
  try{
    const {id}=await api('command',{device,action,args,requestId:crypto.randomUUID().replaceAll('-','')});
    for(let i=0;i<600;i++){
      await sleep(1500);const value=await api('command/'+id);
      if(value.status==='done'){notice(value.result?.message||'Действие выполнено');return value.result;}
      if(value.status==='failed')throw Error(value.result?.message||'Действие не подтверждено. Проверьте журнал.');
      if(value.status==='expired')throw Error('Запрос истёк без выполнения. Проверьте связь с компьютером.');
    }
    throw Error('Результат не получен. Проверьте журнал и очередь Windows. Не повторяйте печать до проверки.');
  }finally{busy=false;await refresh().catch(()=>{});renderDisabled();}
}
function action(fn){return async event=>{try{await fn(event);}catch(e){notice(e.message,true);}};}
function currentPeriod(){return range||{from:stamp($('historyStart').value),to:253402289999};}
function paint(el,colors){el.style.backgroundColor=colors?.[0]||'#e4e8ef';el.style.color=colors?.[1]||'#111936';}
function renderDisabled(){const available=online()&&verified&&!snapshot?.busy;for(const id of ['autoPrint','refreshArticles','printAll','printSelected','saveRoutes','archive','openArchive','startup','refreshPrinters'])$(id).disabled=busy||!available; $('refresh').disabled=busy;$('applyStart').disabled=busy; if(carrier==='all')$('printAll').disabled=true;for(const b of document.querySelectorAll('.printicon'))b.disabled=busy||!available||b.dataset.unready==='true';}
async function refresh(force=false){
  verified=false;renderDisabled();
  const data=await api('devices');devices=data.devices;
  if(!devices.some(v=>v.id===device))device=devices.find(v=>v.online)?.id||devices[0]?.id||'';
  const selector=$('device');selector.replaceChildren();
  for(const v of devices){const o=node('option',v.name+(v.online?' · на связи':' · не на связи'));o.value=v.id;selector.append(o);}selector.value=device;
  $('onboarding').hidden=online();
  $('deviceState').textContent=online()?'Модуль печати работает самостоятельно':'Просмотр на сервере · модуль печати не на связи';
  let local=null;
  if(online())try{local=await api('snapshot?device='+encodeURIComponent(device));}catch{devices=devices.map(v=>v.id===device?{...v,online:false}:v);}
  if(local&&hydratedDevice!==device){
    const date=local.historyStart?.split('.').reverse().join('-');if(/^\d{4}-\d{2}-\d{2}$/.test(date||''))$('historyStart').value=date;
    hydratedDevice=device;range=null;skuFilter=null;selected.clear();
  }
  const from=Math.min(currentPeriod().from,stamp($('historyStart').value));
  if(force||!cloud||cloudFrom!==from||Date.now()-cloudAt>60000){
    cloud=await api('catalog?from='+Math.floor(from));cloudAt=Date.now();cloudFrom=from;
  }
  const history=await api('history');verified=true;
  const items=new Map((cloud?.items||[]).map(v=>[String(v.id),v]));
  for(const v of local?.items||[]){
    const fresh=items.get(String(v.id));if(!fresh)continue;
    const uncertain=v.statusText==='Печать не подтверждена';
    items.set(String(v.id),{...v,...fresh,colors:JSON.stringify(v.skus)===JSON.stringify(fresh.skus)?v.colors:fresh.colors,
      confirmed:uncertain?false:fresh.confirmed||v.confirmed,canPrint:fresh.canPrint&&v.canPrint,
      statusText:uncertain?v.statusText:fresh.statusText,reasons:[...new Set([...fresh.reasons,...v.reasons])]});
  }
  for(const [id,v] of items){
    const uncertain=v.statusText==='Печать не подтверждена';
    if(history.printed[id]&&!uncertain){v.confirmed=true;v.statusText='Передано драйверу';}
    else if(history.uncertain[id]&&!history.printed[id]){v.confirmed=false;v.canPrint=false;v.statusText='Печать не подтверждена';}
  }
  const journal=[...(local?.journal||[])],known=new Set(journal.map(v=>[v.id,v.at,v.printer||''].join('|')));
  for(const v of history.events||[])if(!known.has([v.id,v.at,v.printer||''].join('|')))journal.push(v);
  journal.sort((a,b)=>(b.at||0)-(a.at||0));
  snapshot={printers:[],printer:'',articles:[],routes:{enabled:false,routes:[]},startup:false,autoPrint:false,...local,
    items:[...items.values()],journal,connection:local?.connection||'amoCRM и общая история · сервер',archive:local?.archive||'Архив PDF доступен на компьютере печати'};
  $('connection').textContent=snapshot.connection;$('autoPrint').checked=snapshot.autoPrint;
  $('archiveStatus').textContent=snapshot.archive;$('startup').checked=snapshot.startup;
  if(!$('settingsDialog').open)fillSettings();
  render();renderDisabled();
}

function render(){
  if(!snapshot)return;
  allPeriod=filterItems(snapshot.items,{...currentPeriod(),query});
  deliveryItems=allPeriod.filter(v=>carrier==='all'||v.deliveryService===carrier);
  let articlesSource=carrier==='all'?deliveryItems.filter(v=>!v.confirmed):deliveryItems;
  const available=new Set(articleCounts(articlesSource).map(v=>v[0]));
  if(skuFilter&&!Array.from(skuFilter).some(s=>available.has(s)))skuFilter=null;
  $('articles').replaceChildren();
  for(const [sku,value] of articleCounts(articlesSource)){
    const box=node('article',undefined,'article'+(skuFilter?.has(sku)?' chosen':''));paint(box,value.colors);
    const label=node('button',sku||'Без артикула','sku');label.setAttribute('aria-pressed',String(!!skuFilter?.has(sku)));label.onclick=()=>{if(!skuFilter)skuFilter=new Set();if(skuFilter.has(sku))skuFilter.delete(sku);else skuFilter.add(sku);if(!skuFilter.size)skuFilter=null;render();};
    box.append(label,node('small',`${value.count} заявок · ✓ ${value.printed}`));
    const print=node('button',undefined,'printicon');print.innerHTML=printerIcon;print.title='Печатать артикул '+sku;print.disabled=busy||!sku;print.dataset.unready=String(!sku);print.onclick=action(()=>preparePrint(deliveryItems.filter(v=>v.skus.includes(sku)),'article',`Артикул: ${sku}`));box.append(print);$('articles').append(box);
  }
  $('resetArticles').hidden=!skuFilter;
  const filtered=filterItems(deliveryItems,{...currentPeriod(),skus:skuFilter});
  for(const b of $('statuses').querySelectorAll('button')){const s=b.dataset.status;b.classList.toggle('active',status===s);b.setAttribute('aria-pressed',String(status===s));b.querySelector('span').textContent=`(${s==='all'?filtered.length:filtered.filter(v=>v.confirmed===(s==='printed')).length})`;}
  for(const b of $('carriers').querySelectorAll('button')){b.classList.toggle('active',carrier===b.dataset.carrier);b.setAttribute('aria-pressed',String(carrier===b.dataset.carrier));}
  visible=filtered.filter(v=>status==='all'||v.confirmed===(status==='printed'));
  $('selectionControls').hidden=!selection;$('selection').textContent=selection?'Завершить выбор':'Выбрать несколько';
  $('printSelected').textContent=`Печать выбранных (${visible.filter(v=>selected.has(String(v.id))).length})`;
  const orders=$('orders');orders.replaceChildren();
  if(!visible.length)orders.append(node('div','Заявок по выбранным условиям нет.','empty'));
  const days=new Map();
  for(const v of visible){const d=day(v.createdAt);const list=days.get(d)||[];list.push(v);days.set(d,list);}
  for(const [d,items] of [...days].sort((a,b)=>b[0].localeCompare(a[0]))){
    orders.append(node('h3',d.split('-').reverse().join('.')+` · ${items.length} заявок`,'daytitle'));
    const grid=node('div',undefined,'ordergrid');
    for(const item of items.sort((a,b)=>a.colors[0].localeCompare(b.colors[0])||a.createdAt-b.createdAt||a.id-b.id)){
      const card=node('article',undefined,'order '+item.deliveryService+(selected.has(String(item.id))?' selected':''));paint(card,item.colors);
      card.title=title(item);const digits=String(item.orderNumber||item.id).replace(/\D/g,'').slice(-4);
      card.append(node('div',digits,'digits'),node('div',title(item),'number'));
      const sku=node('div',undefined,'skuline');sku.append(node('span',item.skus.join('; ')||'Без артикула'));
      if(item.skus.length){const copy=node('button',undefined,'copy');copy.innerHTML=copyIcon;copy.title='Скопировать полный артикул';copy.onclick=action(async e=>{e.stopPropagation();await navigator.clipboard.writeText(item.skus.join('; '));notice('Артикул скопирован.');});sku.append(copy);}card.append(sku);
      const buttons=node('div',undefined,'cardactions');const mark=node('span',item.confirmed?'✓':'!',item.confirmed?'statusmark ok':'statusmark');mark.title=item.statusText;buttons.append(mark);
      const reason=node('button','Причина');reason.onclick=e=>{e.stopPropagation();$('reasons').replaceChildren(node('h3',title(item)),...item.reasons.map(t=>node('p',t)));$('reasonDialog').showModal();};buttons.append(reason);if(item.hasLabel){const pdf=node('a','PDF');pdf.href='/api/browser/label/'+item.id;pdf.download='label-'+item.id+'.pdf';pdf.onclick=e=>e.stopPropagation();buttons.append(pdf);}
      const print=node('button',undefined,'printicon');print.innerHTML=printerIcon;print.title='Печатать одну этикетку';print.disabled=!item.canPrint||busy;print.dataset.unready=String(!item.canPrint);print.onclick=action(async e=>{e.stopPropagation();await preparePrint([item],'selected',title(item));});buttons.append(print);card.append(buttons);
      if(selection){card.tabIndex=0;card.setAttribute('role','checkbox');card.setAttribute('aria-checked',String(selected.has(String(item.id))));const toggle=()=>{if(!item.canPrint)return;const id=String(item.id);selected.has(id)?selected.delete(id):selected.add(id);render();};card.onclick=toggle;card.onkeydown=e=>{if(e.target===card&&[' ','Enter'].includes(e.key)){e.preventDefault();toggle();}};}
      grid.append(card);
    }orders.append(grid);
  }
  renderDisabled();
}
async function preparePrint(items,mode,context){
  const ready=orderedGroups(items.filter(v=>v.canPrint));
  if(!ready.length)throw Error('Готовых этикеток нет. Проверьте причины на карточках.');
  const result=await command('plan',{ids:ready.map(v=>v.id),mode});plan=result.plan;
  const parts=[node('h3',context),node('p',`Компьютер: ${devices.find(v=>v.id===device)?.name}. Напечатать ${result.count} этикеток — по одному экземпляру каждой заявки?`),...Object.entries(result.printers).map(([name,count])=>node('p',`${name}: ${count} шт.`))];
  if(result.repeats)parts.push(node('p',`Уже отправлены: ${result.repeats}. Будут напечатаны дополнительные экземпляры.`,'warning'));
  if(items.length!==ready.length)parts.push(node('p',`Без готовой этикетки или с неопределённой печатью: ${items.length-ready.length}. Они пропущены.`));
  parts.push(node('p','Все этикетки и штрихкоды будут проверены до отправки. Неопределённые задания автоматически не повторяются.'));
  $('confirmation').replaceChildren(...parts);$('confirmDialog').showModal();
}
function fillSettings(){
  if(!snapshot)return;
  routesDraft=structuredClone(snapshot.routes.slots||snapshot.routes.routes||[]);while(routesDraft.length<4)routesDraft.push({printer:'',skus:[]});
  const select=$('defaultPrinter');select.replaceChildren();for(const name of snapshot.printers){const o=node('option',name);o.value=name;select.append(o);}select.value=snapshot.printer;
  for(const [id,service] of [['deliveryYandex','yandex'],['deliveryCdek','cdek']]){
    const el=$(id);el.replaceChildren();const empty=node('option','По артикулам');empty.value='';el.append(empty);
    for(const name of new Set([...snapshot.printers,...(snapshot.routes.deliveryPrinters?.[service]?[snapshot.routes.deliveryPrinters[service]]:[])])){const option=node('option',name+(snapshot.printers.includes(name)?'':' · не установлен'));option.value=name;el.append(option);}
    el.value=snapshot.routes.deliveryPrinters?.[service]||'';
  }
  drawRoutes();renderJournal();
}
function drawRoutes(){
  $('routes').replaceChildren();const skus=[...new Set([...snapshot.articles,...snapshot.items.flatMap(v=>v.skus),...routesDraft.flatMap(v=>v.skus)])].sort();
  routesDraft.forEach((slot,index)=>{
    const row=node('div',undefined,'route'),left=node('div');left.append(node('h3',`Принтер ${index+1}`));const select=node('select');select.setAttribute('aria-label',`Принтер ${index+1}`);
    const empty=node('option','Не выбран');empty.value='';select.append(empty);
    for(const name of snapshot.printers){const o=node('option',name);o.value=name;o.disabled=routesDraft.some((v,i)=>i!==index&&v.printer===name);select.append(o);}select.value=slot.printer;
    select.onchange=()=>{slot.printer=select.value;drawRoutes();};left.append(select);const clear=node('button','Очистить');clear.onclick=()=>{slot.printer='';slot.skus=[];drawRoutes();};left.append(clear);row.append(left);
    const chips=node('div',undefined,'routechips');for(const sku of skus){const owner=routesDraft.findIndex(v=>v.skus.includes(sku));if(owner!==-1&&owner!==index)continue;const label=node('label');const check=node('input');check.type='checkbox';check.checked=slot.skus.includes(sku);check.disabled=!slot.printer;check.onchange=()=>{slot.skus=check.checked?[...slot.skus,sku]:slot.skus.filter(s=>s!==sku);drawRoutes();};label.append(check,document.createTextNode(' '+sku));chips.append(label);}row.append(chips);$('routes').append(row);
  });
  $('routingStatus').textContent=snapshot.routes.error|| (snapshot.routes.enabled?'Назначения включены. Нераспределённые артикулы не печатаются.':'Для доставки без отдельного принтера действуют настройки по артикулам; до первой настройки — 4BARCODE 3B-T361U.');
}
function renderJournal(){
  if(!snapshot)return;const q=$('journalSearch').value.trim().toLowerCase();const entries=snapshot.journal.filter(v=>!q||[v.orderNumber,v.id,...(v.skus||[])].some(s=>String(s||'').toLowerCase().includes(q)));
  $('journalSummary').textContent=`Отправлено этикеток: ${entries.filter(v=>v.status==='submitted').length}`;
  const table=node('table'),head=node('thead'),hr=node('tr');for(const name of ['Время МСК','Заявка','Артикулы','Принтер','Режим','Результат'])hr.append(node('th',name));head.append(hr);table.append(head);const body=node('tbody');let previous='';
  for(const v of entries){const d=v.at?day(v.at):'unknown';if(d!==previous){const tr=node('tr',undefined,'journalday'),td=node('td',(d==='unknown'?'Дата не сохранена':d.split('-').reverse().join('.')));td.colSpan=6;tr.append(td);body.append(tr);previous=d;}const tr=node('tr',undefined,v.status==='submitted'?'':'uncertain');for(const value of [v.at?new Date(v.at*1000).toLocaleTimeString('ru-RU',{timeZone:'Europe/Moscow'}):'—',title(v),(v.skus||[]).join('; '),v.printer||'Не записан',v.mode==='manual'?'Ручная':'Авто',v.status==='submitted'?'Передано драйверу':'Нет подтверждения'])tr.append(node('td',value));body.append(tr);}table.append(body);$('journal').replaceChildren(table);
}
const today=day(Date.now()/1000);$('from').value=today;$('to').value=today;
for(const b of $('carriers').querySelectorAll('button'))b.onclick=()=>{carrier=b.dataset.carrier;skuFilter=null;selected.clear();render();};
for(const b of $('statuses').querySelectorAll('button'))b.onclick=action(async()=>{status=b.dataset.status;render();await refresh(true);});
$('history').onclick=()=>{carrier='all';skuFilter=null;render();};
$('selection').onclick=()=>{selection=!selection;render();};$('selectAll').onclick=()=>{for(const v of visible)if(v.canPrint)selected.add(String(v.id));render();};$('clearSelection').onclick=()=>{selected.clear();render();};
$('resetArticles').onclick=()=>{skuFilter=null;render();};
$('period').onclick=action(async()=>{const from=stamp($('from').value,$('fromTime').value),to=stamp($('to').value,$('toTime').value)+59;if(!Number.isFinite(from)||!Number.isFinite(to)||from>to)throw Error('Проверьте даты и время периода');range={from,to};render();if(from<stamp($('historyStart').value)&&online())await command('refresh',{from});await refresh(true);});
$('today').onclick=()=>{const d=day(Date.now()/1000);$('from').value=d;$('to').value=d;$('fromTime').value='00:00';$('toTime').value='23:59';range={from:stamp(d),to:stamp(d,'23:59')+59};render();};
$('twoHours').onclick=()=>{const now=Date.now()/1000;range={from:now-7200,to:now};render();};
$('applyStart').onclick=action(async()=>{if(!$('historyStart').value)throw Error('Выберите дату начала');range=null;skuFilter=null;selected.clear();if(online())await command('refresh',{historyStart:$('historyStart').value.split('-').reverse().join('.')});await refresh(true);});
$('historyStart').onchange=$('applyStart').onclick;
$('searchForm').onsubmit=e=>{e.preventDefault();query=$('search').value.trim();carrier='all';skuFilter=null;range=null;render();};$('resetSearch').onclick=()=>{query='';$('search').value='';render();};
$('device').onchange=action(async()=>{if(busy)throw Error('Дождитесь завершения действия');device=$('device').value;localStorage.setItem('snowbrick-device',device);snapshot=null;$('orders').replaceChildren();await refresh();});
$('refresh').onclick=action(async()=>{if(online())await command('refresh');await refresh(true);});$('refreshArticles').onclick=action(()=>command('articles'));
$('printAll').onclick=action(()=>preparePrint(deliveryItems,'carrier',carrier==='yandex'?'Яндекс доставка · все заявки выбранного периода':'СДЭК доставка · все заявки выбранного периода'));
$('printSelected').onclick=action(()=>preparePrint(visible.filter(v=>selected.has(String(v.id))),'selected','Выбранные заявки'));
$('confirmPrint').onclick=action(async()=>{const token=plan;plan=null;$('confirmDialog').close();if(!token)return;const result=await command('print',{plan:token});notice(`Отправлено этикеток: ${result.submitted}.`+(result.failed?' Партия остановлена. Проверьте очередь и журнал, автоматического повтора нет.':''),result.failed);selected.clear();render();});
$('autoPrint').onchange=action(async()=>{const enabled=$('autoPrint').checked;$('autoPrint').checked=!!snapshot?.autoPrint;if(!confirm(`${enabled?'Включить':'Выключить'} автоматическую печать на компьютере «${devices.find(v=>v.id===device)?.name}»?`))return;await command('auto',{enabled});});
$('settings').onclick=()=>{fillSettings();$('settingsDialog').showModal();};
for(const b of document.querySelectorAll('[data-close]'))b.onclick=()=>$(b.dataset.close).close();
for(const b of $('settingsTabs').querySelectorAll('button'))b.onclick=()=>{for(const s of document.querySelectorAll('.settingspage'))s.hidden=s.id!==b.dataset.page;for(const x of $('settingsTabs').querySelectorAll('button'))x.classList.toggle('active',x===b);if(b.dataset.page==='journalPage')renderJournal();};
$('saveRoutes').onclick=action(()=>command('settings',{printer:$('defaultPrinter').value,routes:{enabled:snapshot.routes.enabled||routesDraft.some(v=>v.skus.length),slots:routesDraft,deliveryPrinters:Object.fromEntries([['yandex',$('deliveryYandex').value],['cdek',$('deliveryCdek').value]].filter(([,v])=>v))}}));
$('refreshPrinters').onclick=action(async()=>{await command('printers');fillSettings();});
$('startup').onchange=action(()=>command('startup',{enabled:$('startup').checked}));$('archive').onclick=action(()=>command('archive'));$('openArchive').onclick=action(()=>command('openArchive'));
$('journalSearch').oninput=renderJournal;$('refreshJournal').onclick=action(async()=>{await refresh(true);renderJournal();});
$('logout').onclick=action(async()=>{await fetch('/api/auth/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});location.assign('/login');});
await refresh().catch(e=>notice(e.message,true));setInterval(()=>{if(!busy)refresh().catch(()=>notice('Нет связи с сайтом. Показаны сохранённые карточки.',true));},5000);
