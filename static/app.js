(() => {
  "use strict";
  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => [...root.querySelectorAll(s)];
  const S = { me: null, data: null, view: "home", orderId: null, filter: "all", search: "", areaFilter:"", equipmentFilter:"", workerFilter:"", priorityFilter:"", timer: null, installPrompt: null, report: null, session: 0, refreshRequest: 0, drawerVersion: 0, drawerRequest: 0, drawerOrderId: null, drawerStatus: null, viewVersion: 0, reportRequest: 0, ratingFrom:"", ratingTo:"", ratingShift:"", reportFrom:"", reportTo:"", reportShift:"", reportBrigade:"", completing: new Set(), uploading: new Set(), creatingOrder: false };
  const STATUS_RU = {issued:"Выдан",accepted:"Принят",queued:"В очереди",rejected:"Отклонён",in_progress:"В работе",paused:"Приостановлен",executed:"Исполнено",ai_review:"Проверка ИИ",rework:"Доработка",closed:"Закрыт"};
  const EVENT_RU = {issued:"Выдал наряд",accept:"Принял наряд",queue:"Поставил в очередь",reject:"Отклонил наряд",start:"Начал работу",pause:"Приостановил работу",resume:"Продолжил работу",complete:"Зафиксировал исполнение",ai_check:"Проверил отчёт",request_rework:"Вернул на доработку",close:"Принял и закрыл",reissue:"Выдал повторно",reassigned:"Переназначил",cancel:"Отменил наряд",priority_changed:"Изменил приоритет",photo_uploaded:"Загрузил фото",rating_adjusted:"Изменил оценку",rejection_classified:"Классифицировал отказ",acceptance_escalated:"Эскалация принятия",deadline_reminder:"Напоминание о сроке",deadline_escalated:"Эскалация просрочки",deadline_repeat:"Повторное сообщение о просрочке"};
  const ESC = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  const initials = (s="") => s.trim().split(/\s+/).slice(0,2).map(x=>x[0]||"").join("").toUpperCase() || "Н";
  const dateFmt = (v, time=true) => { if(!v) return "—"; const d=new Date(v); if(Number.isNaN(d.valueOf())) return "—"; return new Intl.DateTimeFormat("ru-RU",{day:"2-digit",month:"short",...(time?{hour:"2-digit",minute:"2-digit"}:{year:"numeric"})}).format(d); };
  const ago = v => { if(!v)return ""; const m=Math.max(0,Math.round((Date.now()-new Date(v).valueOf())/60000)); return m<1?"только что":m<60?`${m} мин назад`:`${Math.floor(m/60)} ч назад`; };
  const role = () => S.me?.role || "worker";
  const orders = () => S.data?.orders || [];
  const statuses = o => STATUS_RU[o.status] || o.status;
  const formatNum = (n, suffix="") => n == null ? "—" : `${n}${suffix}`;
  const liveStatuses = ["issued","accepted","queued","in_progress","paused","executed","ai_review","rework"];
  const doneStatuses = ["closed","rejected"];

  // Async work keeps its initiating session/order; navigation must never retarget a write.
  const context = () => ({session:S.session, drawer:S.drawerVersion, orderId:S.orderId});
  const sameSession = c => c.session===S.session && !!S.me;
  const sameDrawer = c => sameSession(c) && c.drawer===S.drawerVersion && c.orderId===S.orderId;

  async function api(path, method="GET", body=null) {
    const session=S.session;
    const headers = {"Accept":"application/json"};
    if(body !== null) headers["Content-Type"]="application/json";
    if(method !== "GET" && S.me?.csrf) headers["X-CSRF-Token"]=S.me.csrf;
    const res = await fetch(path,{method,headers,credentials:"same-origin",cache:"no-store",...(body!==null?{body:JSON.stringify(body)}:{})});
    const type = res.headers.get("content-type")||"";
    const payload = type.includes("json") ? await res.json() : {};
    if(session!==S.session) throw new Error("Запрос относится к предыдущей сессии.");
    if(res.status===401 && path!=="/api/login") { logoutLocal(); throw new Error("Сессия завершилась — войдите снова."); }
    if(!res.ok) throw new Error(payload.error || `Ошибка запроса (${res.status})`);
    return payload;
  }
  function toast(message, isError=false) {
    const node=document.createElement("div"); node.className=`toast${isError?" error":""}`; node.textContent=message; $("#toast-region").append(node); setTimeout(()=>node.remove(),4200);
  }
  function logoutLocal(){ S.session++;S.me=null;S.data=null;S.view="home";S.report=null;S.completing.clear();S.uploading.clear();S.creatingOrder=false;closeDrawer();clearInterval(S.timer);$("#notification-popover")?.remove();$("#view-root").innerHTML="";$("#detail-drawer").innerHTML="";$("#app").classList.add("hidden");$("#login-screen").classList.remove("hidden"); }

  async function login(event){
    event.preventDefault(); S.session++; $("#login-error").textContent="";
    const button=$("#login-form button[type=submit]"); button.disabled=true; button.textContent="Проверяем доступ…";
    try { const result=await api("/api/login","POST",{username:$("#username").value.trim(),password:$("#password").value});
      S.me=result.user; await startApp();
    } catch(err){ $("#login-error").textContent=err.message; }
    finally {button.disabled=false;button.innerHTML='Войти в систему <span aria-hidden="true">↗</span>';}
  }
  async function startApp(){
    $("#login-screen").classList.add("hidden");$("#app").classList.remove("hidden");
    const session=S.session;await refresh();if(session!==S.session||!S.me)return;clearInterval(S.timer);S.timer=setInterval(()=>refresh(true),4000);
    if("serviceWorker" in navigator && (location.protocol==="https:" || location.hostname==="localhost" || location.hostname==="127.0.0.1")) navigator.serviceWorker.register("/static/sw.js").catch(()=>{});
  }
  async function refresh(silent=false){
    if(!S.me)return;
    const c=context(), request=++S.refreshRequest;
    try {
      const params=new URLSearchParams();if(S.ratingFrom)params.set("rating_from",S.ratingFrom);if(S.ratingTo)params.set("rating_to",S.ratingTo);if(S.ratingShift)params.set("shift_code",S.ratingShift);const data=await api(`/api/bootstrap${params.size?`?${params}`:""}`);if(!sameSession(c)||request!==S.refreshRequest)return;
      S.data=data;S.me=data.user;$("#offline-banner").classList.add("hidden");
      syncChrome();if(S.view!=="reports"||!$("#report-result"))render();
      if(S.orderId)await refreshDrawer(true);
    } catch(err){
      if(!sameSession(c)||request!==S.refreshRequest)return;
      if(!navigator.onLine) $("#offline-banner").classList.remove("hidden");
      else if(!silent) toast(err.message,true);
    }
  }
  function syncChrome(){
    $("#sidebar-name").textContent=S.me.display_name;$("#sidebar-role").textContent=S.me.role_label;$("#top-avatar").textContent=initials(S.me.display_name);$("#sidebar-avatar").textContent=initials(S.me.display_name);
    const unseen=(S.data.notifications||[]).filter(n=>!n.read_at).length; const badge=$("#notification-count"); badge.textContent=unseen;badge.classList.toggle("hidden",!unseen);
    const roleAllowed={worker:["home","orders","reports"],master:["home","orders","team","reports","audit"],manager:["home","orders","team","reports","audit"]}[role()];
    $$(".nav-item").forEach(b=>{b.classList.toggle("hidden",!roleAllowed.includes(b.dataset.view));b.classList.toggle("active",b.dataset.view===S.view);});
    const shown=orders().filter(o=>liveStatuses.includes(o.status)).length;$("#nav-orders").textContent=shown;
    $("#sidebar").classList.remove("mobile-open");
    $("#breadcrumb-current").textContent=({home:"Обзор",orders:"Наряды",team:"Команда",reports:"Отчёты",audit:"Журнал"})[S.view]||"Обзор";
  }
  function render(){ if(!S.data)return; S.viewVersion++;const root=$("#view-root");
    if(S.view==="orders") root.innerHTML=renderOrders(); else if(S.view==="team")root.innerHTML=renderTeam(); else if(S.view==="reports")root.innerHTML=renderReports(); else if(S.view==="audit")root.innerHTML='<div class="loading-state"><span class="loader"></span>Загружаем журнал…</div>'; else root.innerHTML=renderHome();
    if(S.view==="audit")loadAudit();
    if(S.view==="reports")bindReportControls();
     if(S.view==="team")bindTeamControls();
     if(S.view==="home"&&role()==="worker")bindWorkerRatingControls();
    bindDynamicControls();
  }
  function pageHeading(kicker,title,sub,actions="") {return `<div class="page-heading"><div><span class="section-kicker">${ESC(kicker)}</span><h1>${ESC(title)}</h1><p>${ESC(sub)}</p></div><div class="heading-actions">${actions}</div></div>`;}
  function stat(label,value,caption,icon,alert=false){return `<article class="stat-card${alert?" alert":""}"><div class="stat-head"><span>${ESC(label)}</span><span class="stat-icon">${icon}</span></div><div class="stat-number">${ESC(value)}</div><span class="stat-caption">${ESC(caption)}</span></article>`;}
  function badge(o){return `<span class="badge status-${ESC(o.status)}">${ESC(o.cancelled_by_master?"Отменён мастером":statuses(o))}</span>`;}
  function priority(o){return `<span class="priority${o.priority==="emergency"?" emergency":""}">${ESC(o.priority_label)}</span>`;}
  function orderRow(o){return `<div class="order-row" data-open-order="${o.id}"><span class="row-strip${o.priority==="emergency"?" emergency":o.is_overdue?" overdue":""}"></span><div><div class="row-title"><b>${ESC(o.title)}</b><code>${ESC(o.code)}</code>${o.is_overdue?'<span class="badge status-rework">Просрочен</span>':''}</div><div class="row-meta">${ESC(o.equipment.name)} · ${ESC(o.area)} · ${ESC(o.worker.display_name)}</div></div><div class="row-right">${badge(o)}<span class="row-meta">до ${dateFmt(o.due_at)}</span></div></div>`;}
  function boardCard(o){return `<article class="board-card" data-open-order="${o.id}">${badge(o)}<h3>${ESC(o.title)}</h3><p>${ESC(o.code)} · ${ESC(o.equipment.name)}</p><div class="board-card-foot"><span>${ESC(o.worker.display_name)}</span><span>${o.is_overdue?"⏱ Просрочен":dateFmt(o.due_at)}</span></div></article>`;}
  function renderHome(){
    const all=orders(), current=all.filter(o=>liveStatuses.includes(o.status)), late=current.filter(o=>o.is_overdue), running=current.filter(o=>["in_progress","paused"].includes(o.status)), waiting=current.filter(o=>["issued","accepted","queued","rework"].includes(o.status));
    const master=role()==="master", worker=role()==="worker", manager=role()==="manager";
    const title=worker?`Здравствуйте, ${S.me.display_name.split(" ")[0]}`:master?"Панель мастера":"Сводка участка";
    let action=master?'<button class="button button-primary" data-new-order>＋ Выдать наряд</button>':'';
    let content=`${pageHeading(master?"СМЕНА · МАСТЕР":worker?"МОЯ СМЕНА":"READ-ONLY · РУКОВОДИТЕЛЬ",title,worker?"Ваша очередь, работа и сроки — в одном окне.":"Текущая картина нарядов по синтетическим данным.",action)}
      <div class="grid stats-grid">${stat("Открытые наряды",current.length,"всего в работе","▤")}${stat(worker?"Моя очередь":"В работе",worker?waiting.length:running.length,worker?"ожидают начала":"исполняются или приостановлены","◷")}${stat("Просрочены",late.length,"до статуса «Исполнено»","!",late.length>0)}${stat(master?"Свободные исполнители":"Закрыто",master?(S.data.free_workers||[]).filter(x=>x.availability==="free").length:all.filter(o=>o.status==="closed").length,master?"по текущей загрузке":"в этой выборке","♧")}</div>`;
    content+=`<div class="grid content-grid"><section class="panel"><div class="panel-header"><div><h2 class="panel-title">${worker?"Ближайшие действия":"Наряды, требующие внимания"}</h2><p class="panel-subtitle">${late.length?`${late.length} просрочено · `:""}обновление каждые 4 секунды</p></div><button class="text-link" data-nav="orders">Все наряды ↗</button></div><div class="order-list">${(worker?current.filter(o=>["issued","queued","accepted","in_progress","paused","rework"].includes(o.status)):current.filter(o=>o.is_overdue||["issued","executed","ai_review","paused","rework"].includes(o.status))).slice(0,8).map(orderRow).join("")||'<div class="empty-state">Сейчас нет нарядов, требующих внимания.</div>'}</div></section>
      <div class="dashboard-side"><section class="panel"><div class="panel-header"><div><h2 class="panel-title">Рабочая сводка</h2><p class="panel-subtitle">Синтетический набор · последние 30 дней</p></div></div><div class="kpi-note"><b class="kpi-num">${S.data.constants.areas.length}</b><div><b>участка</b><span>4 производственные зоны в справочнике</span></div></div><div class="kpi-note"><b class="kpi-num">${S.data.constants.equipment.length}</b><div><b>единиц оборудования</b><span>привязаны к участкам</span></div></div><div class="kpi-note"><b class="kpi-num">${all.length}</b><div><b>нарядов в выборке</b><span>550 записей за три месяца и сценарии</span></div></div><div class="notice-box"><strong>Безопасность:</strong> подсказки по тексту и фото не являются допуском, не подтверждают исправность и не разрешают опасные работы.</div></section>
      ${master||manager?`<section class="panel"><div class="panel-header"><div><h2 class="panel-title">Повторяющиеся паттерны</h2><p class="panel-subtitle">Правила по синтетической истории · не прогноз</p></div></div>${(S.data.recurring||[]).slice(0,4).map(x=>`<div class="pattern-row"><span class="pattern-count">${x.count}</span><div><b>${ESC(x.label)}</b><span>${ESC(x.equipment)}</span></div></div>`).join("")||'<div class="empty-state">Недостаточно повторов</div>'}</section>`:""}</div></div>`;
    if(worker){const mine=S.data.my_rating,today=new Date().toISOString().slice(0,10),monthAgo=new Date(Date.now()-29*86400000).toISOString().slice(0,10);content+=`<section class="panel" style="margin-top:14px"><div class="panel-header"><div><h2 class="panel-title">Моя оценка</h2><p class="panel-subtitle">${ESC(mine?.period_from||monthAgo)} — ${ESC(mine?.period_to||today)} UTC · учебная смена ${ESC(S.me.shift_code||"—")}</p></div><b class="panel-title">${mine?.score==null?"—":`${mine.score}/100`}</b></div><div class="report-controls"><label class="field-label">С <input id="my-rating-from" class="field-input" type="date" value="${ESC(S.ratingFrom||monthAgo)}"></label><label class="field-label">По <input id="my-rating-to" class="field-input" type="date" value="${ESC(S.ratingTo||today)}"></label><button class="button button-outline" id="apply-my-rating">Применить период</button></div>${ratingFactors(mine)}</section>`;}
    if(master||manager)content+=`<section class="panel" style="margin-top:14px"><div class="panel-header"><div><h2 class="panel-title">Загрузка исполнителей</h2><p class="panel-subtitle">Статус выводится из назначенных активных нарядов</p></div><button class="text-link" data-nav="team">Команда ↗</button></div><div class="team-grid">${(S.data.members||[]).slice(0,6).map(teamMini).join("")}</div></section>`;
    return content;
  }
  function teamMini(m){return `<div class="team-card"><div class="team-top"><span class="team-avatar">${initials(m.display_name)}</span><div><b>${ESC(m.display_name)}</b><small>Бригада ${ESC(m.brigade||"-")} · ${ESC(m.availability_label)}</small><small>${ESC(m.specialty||"специализация не указана")} · разряд ${m.qualification_level??"—"} · смена ${ESC(m.shift_code||"—")} (синтетика)</small></div></div><div class="team-metrics"><div><b>${m.active_orders||0}</b><span>активных</span></div><div><b>${m.queue_count||0}</b><span>в очереди</span></div><div><b>${m.rating_detail?.score??"-"}</b><span>балл / 100</span></div></div></div>`;}
  const columns = [
    {title:"Выдан / очередь", statuses:["issued","queued"]},
    {title:"Принят", statuses:["accepted"]},
    {title:"В работе / пауза", statuses:["in_progress","paused"]},
    {title:"Проверка / доработка", statuses:["executed","ai_review","rework"]},
    {title:"Закрыт / отклонён", statuses:["closed","rejected"]}
  ];
  function renderOrders(){
    const list=orders().filter(o=>(S.filter==="all"||o.status===S.filter||S.filter==="overdue"&&o.is_overdue)&&(!S.search||`${o.code} ${o.title} ${o.equipment.name} ${o.worker.display_name}`.toLowerCase().includes(S.search.toLowerCase()))&&(!S.areaFilter||String(o.area_id)===S.areaFilter)&&(!S.equipmentFilter||String(o.equipment_id)===S.equipmentFilter)&&(!S.workerFilter||String(o.assigned_to)===S.workerFilter)&&(!S.priorityFilter||o.priority===S.priorityFilter));
    const master=role()==="master";
    const controls=`<button class="button button-outline" data-export-report>⇩ Отчёт дня</button>${master?'<button class="button button-primary" data-new-order>＋ Выдать наряд</button>':''}`;
    const filters=["all","issued","accepted","queued","in_progress","paused","executed","ai_review","rework","closed","rejected","overdue"];
    const areas=S.data.constants.areas,equipment=S.data.constants.equipment,workers=S.data.constants.users.filter(x=>x.role==="worker");
    const toolbar=`<div class="grid" style="gap:9px;margin-bottom:14px"><div class="filter-line" style="margin:0"><div class="board-toolbar">${filters.map(f=>`<button class="filter-chip${S.filter===f?" active":""}" data-filter="${f}">${f==="all"?"Все":f==="overdue"?"Просроченные":STATUS_RU[f]}</button>`).join("")}</div><input class="select-small" id="order-search" placeholder="Поиск по наряду или оборудованию…" value="${ESC(S.search)}"></div><div class="filter-bar"><select class="select-small order-filter" data-kind="area"><option value="">Все участки</option>${areas.map(a=>`<option value="${a.id}" ${S.areaFilter===String(a.id)?"selected":""}>${ESC(a.name)}</option>`).join("")}</select><select class="select-small order-filter" data-kind="equipment"><option value="">Всё оборудование</option>${equipment.map(e=>`<option value="${e.id}" ${S.equipmentFilter===String(e.id)?"selected":""}>${ESC(e.code)} · ${ESC(e.name)}</option>`).join("")}</select><select class="select-small order-filter" data-kind="worker"><option value="">Все исполнители</option>${workers.map(w=>`<option value="${w.id}" ${S.workerFilter===String(w.id)?"selected":""}>${ESC(w.display_name)}</option>`).join("")}</select><select class="select-small order-filter" data-kind="priority"><option value="">Все приоритеты</option>${Object.entries({emergency:"Аварийный",high:"Высокий",normal:"Обычный",planned:"Плановый"}).map(([k,v])=>`<option value="${k}" ${S.priorityFilter===k?"selected":""}>${v}</option>`).join("")}</select><span class="demo-note">${list.length} нарядов в выборке</span></div></div>`;
    const columnsHtml=columns.map(col=>{const group=list.filter(o=>col.statuses.includes(o.status));return `<section class="board-column"><div class="column-title"><span>${ESC(col.title)}</span><span>${group.length}</span></div>${group.slice(0,70).map(boardCard).join("")||'<div class="empty-state">Нет нарядов</div>'}</section>`}).join("");
    const summary=role()==="manager"?"Доступ только для просмотра. Все наряды — синтетические.":master?"Доска мастера · решения о закрытии остаются за мастером.":"Ваши наряды, очередь и история.";
    return `${pageHeading("НАРЯДЫ", "Доска нарядов", summary,controls)}${toolbar}<div class="board-columns">${columnsHtml}</div>`;
  }
  function ratingFactors(detail){
    if(!detail)return '<div class="empty-state">Нет данных за период. Отсутствующие знаменатели не считаются нулём.</div>';
    const names={quality:"Качество · мастер",on_time:"Выполнено в срок",rework_repeat:"Без доработки",quantity_complexity:"Количество + сложность",unjustified_refusal:"Необоснованные отказы"};
    const vals=detail.factors||{}; const weights=detail.factor_weights||{};
    return `<div class="grid" style="gap:8px">${Object.keys(names).map(k=>{const v=vals[k];return `<div><div class="panel-header" style="margin:0 0 4px"><span style="font-size:9px;color:#697a73">${names[k]} <span class="badge">${weights[k]}%</span></span><b style="font-size:9px">${v==null?"нет данных":`${v}/100`}</b></div><div class="progress-line"><span style="width:${v==null?0:v}%"></span></div></div>`}).join("")}</div><p class="demo-note">Вес наблюдаемых факторов перенормируется к 100%; пустой знаменатель исключается. Оценка качества мастера не заменяется ИИ. Подтверждённые повторы сохраняются как факты и не снижают оценку без причинной связи с предыдущим ремонтом. Необоснованные отказы учитываются только после решения мастера.</p>`;
  }
  function renderTeam(){
    const people=S.data.members||[], today=new Date().toISOString().slice(0,10), monthAgo=new Date(Date.now()-29*86400000).toISOString().slice(0,10);
    return `${pageHeading("Команда и загрузка", "Исполнители", "Доступность рассчитывается по нарядам и учебному UTC-графику. Специальность, разряд и смена синтетические; они не подтверждают допуск.")}
      <div class="filter-line"><div class="notice-box" style="max-width:720px"><strong>Формула рейтинга:</strong> качество 40%, срок 20%, отсутствие доработок и явно связанных повторов 20%, объём с коэффициентом сложности 10%, только подтверждённые необоснованные отказы 10%. Вес доступных факторов нормируется до 100%. Повтор учитывается только после явной связи мастером, с основанием и правом отмены.</div></div>
      <div class="filter-line"><label class="field-label">Оценка с <input id="team-rating-from" class="field-input" type="date" value="${ESC(S.ratingFrom||monthAgo)}"></label><label class="field-label">по <input id="team-rating-to" class="field-input" type="date" value="${ESC(S.ratingTo||today)}"></label><label class="field-label">Смена <select id="team-shift-filter" class="field-select"><option value="">все</option>${["A","B","C"].map(x=>`<option value="${x}" ${S.ratingShift===x?"selected":""}>${x} · UTC</option>`).join("")}</select></label><button class="button button-primary" id="apply-team-filters">Применить</button><select id="team-brigade-filter" class="select-small"><option value="all">Все бригады</option><option>A</option><option>B</option><option>C</option></select></div>
      <div class="notice-box">Профили, разряды, бригады и сменный график — вымышленные демонстрационные данные. Это не удостоверения, квалификационная проверка, разрешение на опасные работы или фактическое табелирование.</div>
      <div class="grid team-grid">${people.map(m=>`<article class="team-card team-person" data-brigade="${ESC(m.brigade)}"><div class="team-top"><span class="team-avatar">${initials(m.display_name)}</span><div><b>${ESC(m.display_name)}</b><small>Бригада ${ESC(m.brigade)} · <span class="availability">${ESC(m.availability_label)}</span></small><small>${ESC(m.specialty||"—")} · разряд ${m.qualification_level??"—"} · смена ${ESC(m.shift_code||"—")} (синтетика)</small></div><b style="margin-left:auto;color:#257c61;font:800 17px Manrope">${m.rating_detail?.score??"—"}</b></div><div class="team-metrics"><div><b>${m.active_orders||0}</b><span>активные наряды</span></div><div><b>${m.queue_count||0}</b><span>в очереди</span></div><div><b>${m.rating_detail?.evidence?.closed||0}</b><span>закрыто за период</span></div></div><div class="rating-scale">${ratingFactors(m.rating_detail)}</div></article>`).join("")}</div>`;
  }
  function bindWorkerRatingControls(){
    const from=$("#my-rating-from"),to=$("#my-rating-to");
    from?.addEventListener("input",()=>S.ratingFrom=from.value);to?.addEventListener("input",()=>S.ratingTo=to.value);
    $("#apply-my-rating")?.addEventListener("click",()=>{S.ratingFrom=from?.value||"";S.ratingTo=to?.value||"";if(S.ratingFrom&&S.ratingTo&&S.ratingTo<S.ratingFrom){toast("Дата окончания раньше даты начала.",true);return;}refresh();});
  }
  function bindTeamControls(){
    const from=$("#team-rating-from"),to=$("#team-rating-to"),shift=$("#team-shift-filter");
    [from,to].forEach(el=>el?.addEventListener("input",()=>{if(el===from)S.ratingFrom=el.value;else S.ratingTo=el.value;}));
    shift?.addEventListener("change",()=>S.ratingShift=shift.value);
    $("#apply-team-filters")?.addEventListener("click",()=>{S.ratingFrom=from?.value||"";S.ratingTo=to?.value||"";S.ratingShift=shift?.value||"";if(S.ratingFrom&&S.ratingTo&&S.ratingTo<S.ratingFrom){toast("Дата окончания раньше даты начала.",true);return;}refresh();});
    $("#team-brigade-filter")?.addEventListener("change",e=>$$('.team-person').forEach(c=>c.classList.toggle("hidden",e.target.value!=="all"&&c.dataset.brigade!==e.target.value)));
  }
  function renderReports(){const today=new Date().toISOString().slice(0,10);return `${pageHeading("Наряды и периоды", "Сменные отчёты", "Фильтр по периоду и смене исполнителя. Все даты — UTC; смена в демоданных назначена синтетическому профилю.")}
    <section class="panel"><div class="report-controls"><label class="field-label">С <input id="report-from" class="field-input" type="date" value="${ESC(S.reportFrom||today)}"></label><label class="field-label">По <input id="report-to" class="field-input" type="date" value="${ESC(S.reportTo||today)}"></label><label class="field-label">Бригада <select id="report-brigade" class="field-select"><option value="">все</option>${["A","B","C"].map(x=>`<option value="${x}" ${S.reportBrigade===x?"selected":""}>${x}</option>`).join("")}</select></label><label class="field-label">Смена <select id="report-shift" class="field-select"><option value="">все</option>${["A","B","C"].map(x=>`<option value="${x}" ${S.reportShift===x?"selected":""}>${x} · UTC</option>`).join("")}</select></label><button class="button button-primary" id="load-report">Сформировать отчёт</button></div><div id="report-result"><div class="empty-state">Выберите период и сформируйте отчёт.</div></div></section>`;}
  function bindReportControls(){
    $("#load-report")?.addEventListener("click",loadReport);
    $("#report-result")?.addEventListener("click",()=>{});
    if(S.report&&$("#report-result"))renderReportResult();
  }
  async function loadReport(){
    const from=$("#report-from")?.value||new Date().toISOString().slice(0,10), to=$("#report-to")?.value||from, brigade=$("#report-brigade")?.value||"", shift=$("#report-shift")?.value||"";
    if(to<from){toast("Дата окончания раньше даты начала.",true);return;}
    S.reportFrom=from;S.reportTo=to;S.reportBrigade=brigade;S.reportShift=shift;
    const c=context(), view=S.viewVersion, request=++S.reportRequest;
    const current=()=>sameSession(c)&&S.view==="reports"&&S.viewVersion===view&&S.reportRequest===request;
    $("#report-result").innerHTML='<div class="loading-state"><span class="loader"></span>Собираем сводку…</div>';
    try{const result=await api(`/api/reports?date_from=${encodeURIComponent(from)}&date_to=${encodeURIComponent(to)}&brigade=${encodeURIComponent(brigade)}&shift_code=${encodeURIComponent(shift)}`);if(!current())return;S.report=result;renderReportResult();}
    catch(e){if(current())$("#report-result").innerHTML=`<div class="empty-state">${ESC(e.message)}</div>`;}
  }
  function renderReportResult(){
    if(!S.report)return;
    const summary=S.report.summary,items=S.report.items||[];
    const table=items.length?"<div class=\"report-table-wrap\"><table class=\"report-table\"><thead><tr><th>Наряд</th><th>Оборудование</th><th>Исполнитель</th><th>Результат</th><th>Часы</th><th>Оценка</th></tr></thead><tbody>"+
      items.map(x=>"<tr><td>"+ESC(x.code)+"<br>"+ESC(x.title)+"</td><td>"+ESC(x.equipment)+"<br>"+ESC(x.fault_code||"—")+"</td><td>"+ESC(x.worker)+"<br>Бригада "+ESC(x.brigade||"—")+" · смена "+ESC(x.shift_code||"—")+"</td><td>"+ESC(x.status)+"<br>"+dateFmt(x.completed_at)+"</td><td>"+(x.labor_hours??"—")+"</td><td>"+(x.rating??"—")+"/5</td></tr>").join("")+"</tbody></table></div>":"<div class=\"empty-state\">За выбранный период нет исполненных нарядов.</div>";
    const workerRows=(S.report.worker_totals||[]).map(x=>"<tr><td>"+ESC(x.worker)+"</td><td>"+ESC(x.brigade||"—")+"</td><td>"+ESC(x.shift_code||"—")+"</td><td>"+x.completed+"</td><td>"+x.closed+"</td><td>"+x.labor_hours+"</td></tr>").join("");
    const materialRows=(S.report.material_totals||[]).map(x=>"<tr><td>"+ESC(x.sku)+"</td><td>"+ESC(x.name)+"</td><td>"+x.quantity+" "+ESC(x.unit)+"</td></tr>").join("");
    const headline="<p class=\"demo-note\">"+ESC(summary.date_from)+" — "+ESC(summary.date_to)+" UTC · назначенная синтетическая смена: "+ESC(summary.shift_code)+"</p>";
    const cards="<div class=\"grid report-summary\">"+stat("Выдано",summary.issued,"в периоде","＋")+stat("Исполнено",summary.completed,"зафиксировано исполнителем","▤")+stat("Закрыто",summary.closed,"принято мастером","✓")+stat("Просрочено",summary.late_completions,"среди исполненных","!")+stat("Сейчас просрочено",summary.current_overdue_orders,"открытый срез","◷")+stat("Часы работы",summary.labor_hours,"записанные трудозатраты","◷")+stat("Пауза по журналу",summary.pause_minutes,"это не простой оборудования","Ⅱ")+"</div>";
    const notice="<div class=\"notice-box\"><strong>Правиловая сводка, не LLM:</strong> "+ESC(S.report.ai_summary||("За "+summary.date_from+" — "+summary.date_to+" закрыто "+summary.closed+" из "+summary.completed+" исполненных нарядов."))+(summary.synthetic?" · синтетические данные":"")+"<br>"+ESC(summary.pause_minutes_note||"")+"</div>";
    const workers=workerRows?"<h3>По исполнителям</h3><div class=\"report-table-wrap\"><table class=\"report-table\"><thead><tr><th>Исполнитель</th><th>Бригада</th><th>Смена · синтетика</th><th>Исполнено</th><th>Закрыто</th><th>Часы</th></tr></thead><tbody>"+workerRows+"</tbody></table></div>":"";
    const materials=materialRows?"<h3>Материалы и количество</h3><div class=\"report-table-wrap\"><table class=\"report-table\"><thead><tr><th>Артикул</th><th>Материал</th><th>Итого</th></tr></thead><tbody>"+materialRows+"</tbody></table></div>":"";
    $("#report-result").innerHTML=headline+cards+notice+workers+materials+table;
  }
  async function loadAudit(){
    const c=context(),view=S.viewVersion;const current=()=>sameSession(c)&&S.view==="audit"&&S.viewVersion===view;
    try{const res=await api("/api/audit");if(!current())return;$("#view-root").innerHTML=`${pageHeading("АУДИТ", "Журнал действий", "Серверная запись автора, времени и события; для мастера ограничена его нарядами.")}<section class="panel"><div class="report-table-wrap"><table class="report-table"><thead><tr><th>Когда</th><th>Кто</th><th>Событие</th><th>Наряд</th><th>Данные</th></tr></thead><tbody>${res.items.map(a=>`<tr><td>${dateFmt(a.created_at)}</td><td>${ESC(a.actor_name||"Системный таймер")}</td><td>${ESC(EVENT_RU[a.event]||a.event)}</td><td>${ESC(a.order_code||"—")}</td><td>${ESC(a.payload_json||"{}")}</td></tr>`).join("")}</tbody></table></div></section>`;bindDynamicControls();}
    catch(e){if(current())$("#view-root").innerHTML=`${pageHeading("АУДИТ","Журнал действий","")}<div class="empty-state">${ESC(e.message)}</div>`;}
  }
  function bindDynamicControls(){
    $$("[data-nav]").forEach(b=>b.addEventListener("click",()=>navigate(b.dataset.nav)));
    $$("[data-open-order]").forEach(b=>b.addEventListener("click",()=>openOrder(Number(b.dataset.openOrder))));
    $$("[data-filter]").forEach(b=>b.addEventListener("click",()=>{S.filter=b.dataset.filter;render();}));
    $$(".order-filter").forEach(s=>s.addEventListener("change",()=>{S[`${s.dataset.kind}Filter`]=s.value;render();}));
    $$("[data-new-order]").forEach(b=>b.addEventListener("click",openNewOrder));
    $("#order-search")?.addEventListener("input",e=>{S.search=e.target.value;const pos=e.target.selectionStart;render();const next=$("#order-search");if(next){next.focus();next.setSelectionRange(pos,pos);}});
    $("#team-brigade-filter")?.addEventListener("change",e=>$$('.team-person').forEach(c=>c.classList.toggle("hidden",e.target.value!=="all"&&c.dataset.brigade!==e.target.value)));
    $$("[data-export-report]").forEach(b=>b.addEventListener("click",()=>{navigate("reports");loadReport();}));
  }
  function navigate(view){S.view=view;S.filter="all";syncChrome();render();$("#sidebar").classList.remove("mobile-open");}

  async function openOrder(id){S.drawerVersion++;S.drawerOrderId=null;S.drawerStatus=null;S.orderId=id;$("#drawer-backdrop").classList.remove("hidden");const drawer=$("#detail-drawer");drawer.classList.add("open");drawer.setAttribute("aria-hidden","false");drawer.innerHTML='<div class="loading-state"><span class="loader"></span>Загружаем наряд…</div>';await refreshDrawer();}
  function closeDrawer(){S.drawerVersion++;S.drawerOrderId=null;S.drawerStatus=null;S.orderId=null;$("#detail-drawer").classList.remove("open");$("#detail-drawer").setAttribute("aria-hidden","true");$("#drawer-backdrop").classList.add("hidden");}
  async function refreshDrawer(preserveEdits=false){
    if(!S.orderId)return;
    const c=context(),request=++S.drawerRequest;
    const current=()=>sameDrawer(c)&&request===S.drawerRequest;
    try{
      const detail=await api(`/api/orders/${c.orderId}`);if(!current())return;
      const drawer=$("#detail-drawer"), active=document.activeElement;
      const scroll=$(".drawer-body",drawer)?.scrollTop||0;
      // Reuse live form nodes only while the server still permits the same workflow.
      // This preserves added material rows, values, listeners and caret during polling.
      const forms=preserveEdits&&S.drawerOrderId===c.orderId&&S.drawerStatus===detail.order.status
        ? $$(".action-box",drawer).map(node=>({node,id:$("input[id],select[id],textarea[id]",node)?.id})).filter(x=>x.id) : [];
      renderDrawer(detail);S.drawerOrderId=c.orderId;S.drawerStatus=detail.order.status;
      for(const form of forms)$("#"+form.id,drawer)?.closest(".action-box")?.replaceWith(form.node);
      if(active?.isConnected&&drawer.contains(active))active.focus({preventScroll:true});
      const body=$(".drawer-body",drawer);if(body&&preserveEdits)body.scrollTop=scroll;
    }catch(e){
      if(!current()||(preserveEdits&&S.drawerOrderId===c.orderId))return;
      $("#detail-drawer").innerHTML=`<div class="drawer-head"><b>Наряд</b><button class="drawer-close" data-close-drawer>×</button></div><div class="empty-state">${ESC(e.message)}</div>`;
      $("[data-close-drawer]")?.addEventListener("click",closeDrawer);
    }
  }
  function detailButtons(o){
    if(role()==="manager")return '<p class="demo-note">Режим руководителя: только просмотр.</p>';
    if(role()==="worker"){
      if(o.status==="issued")return `<button class="button button-primary" data-action="accept">Принять в работу</button><button class="button button-outline" data-action="queue">Поставить в очередь</button><button class="button button-danger" data-prompt-action="reject">Отклонить с причиной</button>`;
      if(o.status==="queued")return `<button class="button button-primary" data-action="accept">Принять из очереди</button>`;
      if(o.status==="accepted")return `<button class="button button-primary" data-action="start">Начать исполнение</button>`;
      if(o.status==="rework")return `<button class="button button-primary" data-action="start">Начать доработку</button>`;
      if(o.status==="paused")return `<button class="button button-primary" data-action="resume">Продолжить</button>`;
      if(o.status==="in_progress")return `<button class="button button-warning" data-prompt-action="pause">Приостановить</button><button class="button button-primary" data-toggle-completion>Исполнено · отчёт</button>`;
      if(o.status==="executed")return `<button class="button button-primary" data-action="ai_check">Отправить на проверку ИИ</button><span class="demo-note">Мастер не сможет закрыть наряд до проверки.</span>`;
    }
    if(role()==="master"){
      if(o.status==="ai_review")return `<button class="button button-primary" data-prompt-action="close">Принять и закрыть</button><button class="button button-warning" data-prompt-action="request_rework">Вернуть на доработку</button>`;
      if(o.status==="rejected"&&!o.cancelled_by_master)return `<button class="button button-primary" data-reassign>Переназначить</button>`;
      if(o.status==="closed")return `<button class="button button-soft" data-toggle-rating>Оценка мастера</button>`;
      if(["issued","accepted","queued"].includes(o.status))return `<button class="button button-outline" data-toggle-priority>Изменить приоритет</button><button class="button button-danger" data-prompt-action="cancel">Отменить наряд</button>`;
    }
    return '';
  }
  function renderDrawer(detail){
    const o=detail.order; const photos=o.photos||[]; let ai=null; try{ai=o.ai_result?JSON.parse(o.ai_result):null;}catch{ai={mode:o.ai_mode||"rules-only",verdict:"comments",summary:o.ai_result,issues:[]};}
    const files=photos.length?`<div class="photo-list">${photos.map(p=>{const capture=p.metadata?.capture_datetime?`EXIF: ${ESC(p.metadata.capture_datetime)} · не подтверждено`:"EXIF-даты нет · время съёмки неизвестно";const duplicate=p.duplicate_type==="exact"?"точный дубль":p.duplicate_type==="similar"?"похожий дубль":"уникальный хеш";return `<a class="photo-item" data-phase="${ESC(p.phase)}" href="${ESC(p.url)}" target="_blank" rel="noopener"><img loading="lazy" src="${ESC(p.url)}" alt="Фото ${ESC(p.phase)}"><span>${p.phase==="before"?"До неисправности":"После работы"} · ${duplicate} · ${dateFmt(p.uploaded_at)}</span><small>${capture}</small></a>`}).join("")}</div>`:'<div class="notice-box">Фото пока не приложены. Загрузка не доказывает свежесть съёмки или исправность оборудования.</div>';
    const photoScore=ai?.photo_check?.verifiability_score;
    const aiBlock=ai?`<div class="ai-result${ai.verdict!=="accepted"?" caution":""}"><b>Вердикт: ${ESC({accepted:"Принято · рекомендация",comments:"Замечания",rework:"Требует доработки"}[ai.verdict]||"Результат проверки")}</b><p>${ESC(ai.summary||"")} · режим <strong>${ESC(ai.mode||o.ai_mode||"rules-only")}</strong></p>${ai.issues?.length?`<ul>${ai.issues.map(x=>`<li>${ESC(x)}</li>`).join("")}</ul>`:""}<p>${ESC(ai.photo_check?.explanation||"Текст проверен; мастер принимает окончательное решение.")}</p>${photoScore==null?'<p><strong>Оценка проверяемости фото 1–5:</strong> нет оцениваемого фото.</p>':`<p><strong>Оценка проверяемости фото:</strong> ${photoScore}/5. Это не оценка качества ремонта.${ai.master_confirmation_required?" Нужно подтверждение мастера.":""}</p>`}</div>`:'<div class="notice-box">Проверка ещё не выполнена. Без настроенного API показывается только локальный rules-only результат.</div>';
    const statusFlow=Object.entries(STATUS_RU).map(([k,v])=>`<span class="badge status-${k}" style="opacity:${k===o.status?1:.43}">${ESC(v)}</span>`).join(" ");
    const timeline=(detail.history||[]).slice().reverse().map(h=>`<div class="timeline-item"><b>${ESC(EVENT_RU[h.event]||h.event)}${h.actor_name?` · ${ESC(h.actor_name)}`:""}</b><span>${dateFmt(h.created_at)}${h.payload?.reason?` · ${ESC(h.payload.reason)}`:""}</span></div>`).join("");
    const equipHistory=(detail.equipment_history||[]).slice(0,6).map(h=>`<div class="timeline-item"><b>${ESC(h.code)} · ${ESC(h.title)}</b><span>${dateFmt(h.created_at)} · ${ESC(STATUS_RU[h.status]||h.status)} · ${ESC(h.fault_code||"код не указан")} · ${ESC(h.worker_name||"исполнитель неизвестен")}</span></div>`).join("")||'<p class="demo-note">Истории по этому оборудованию пока нет.</p>';
    const links=detail.repeat_links||[],activeLink=links.find(x=>x.active), repeatCandidates=(detail.equipment_history||[]).filter(h=>o.status==="closed"&&h.status==="closed"&&o.fault_code_id&&h.fault_code_id===o.fault_code_id&&h.completed_at&&Date.parse(o.created_at)>=Date.parse(h.completed_at)&&Date.parse(o.created_at)<=Date.parse(h.completed_at)+7*86400000);
    const repeatPanel=role()==="master"&&o.status==="closed"?`<div class="action-box"><h3>Повторный отказ · явная связь мастера</h3>${activeLink?`<p>Связан с <b>${ESC(activeLink.previous_code)}</b>; прежний исполнитель: ${ESC(activeLink.previous_worker)}; связал ${ESC(activeLink.linked_by)}. Основание: ${ESC(activeLink.reason)}. Фактор рейтинга пересчитан по этой ручной атрибуции.</p><label class="field-label">Основание отмены<textarea id="repeat-revoke-reason" class="field-textarea" placeholder="Почему связь нужно отменить?"></textarea></label><button class="button button-outline" data-revoke-repeat>Отменить связь</button>`:links.length?`<p>Последняя связь отменена ${dateFmt(links[0].revoked_at)} · ${ESC(links[0].revoke_reason||"")}.</p><p>Активной связи нет, повторный фактор не применяется.</p>`:`<p>Автоматической связи и штрафа нет. Если мастер установил повтор в течение 7 дней на том же оборудовании и коде неисправности, выберите прежний наряд и укажите основание. Связь попадёт в аудит; её можно отменить.</p><label class="field-label">Прежний закрытый наряд<select id="repeat-previous" class="field-select"><option value="">Выберите наряд</option>${repeatCandidates.map(h=>`<option value="${h.id}">${ESC(h.code)} · ${ESC(h.worker_name||"исполнитель") } · ${dateFmt(h.completed_at,false)}</option>`).join("")}</select></label><label class="field-label">Основание мастера<textarea id="repeat-reason" class="field-textarea" placeholder="Фактическое основание, без автоматического вывода о вине"></textarea></label><button class="button button-soft" data-create-repeat ${repeatCandidates.length?"":"disabled"}>Связать повтор вручную</button>`}</div>`:"";
    const materialHTML=o.materials?.length?`<ul>${o.materials.map(m=>`<li>${ESC(m.name)} · ${m.quantity} ${ESC(m.unit)}</li>`).join("")}</ul>`:o.materials_not_used?'<p>Исполнитель указал: материалы не использовались.</p>':'<p>Материалы не записаны.</p>';
    const uploadAllowed=(role()==="master"&&o.status==="issued")||(role()==="worker"&&["in_progress","paused"].includes(o.status));
    const phase=(role()==="master"?"before":"after");
    $("#detail-drawer").innerHTML=`<div class="drawer-head"><div><small>${ESC(o.code)} · ${ESC(o.work_type_label)}</small><b>Карточка наряда</b></div><button class="drawer-close" data-close-drawer aria-label="Закрыть">×</button></div><div class="drawer-body">
      <h1 class="detail-title">${ESC(o.title)}</h1><div class="detail-sub">${ESC(o.description)}</div><div class="detail-badges">${badge(o)}${priority(o)}${o.is_overdue?'<span class="badge status-rework">Просрочен</span>':''}</div>
      <div class="detail-grid"><div class="detail-field"><span>Участок</span><b>${ESC(o.area)}</b></div><div class="detail-field"><span>Оборудование</span><b>${ESC(o.equipment.code)} · ${ESC(o.equipment.name)}</b></div><div class="detail-field"><span>Исполнитель</span><b>${ESC(o.worker.display_name)} · бригада ${ESC(o.worker.brigade||"—")}</b></div><div class="detail-field"><span>Мастер / срок</span><b>${ESC(o.master.display_name)}<br>до ${dateFmt(o.due_at)}</b></div><div class="detail-field"><span>Не принят более</span><b>${o.acceptance_limit_minutes} мин ${o.priority==="emergency"?"· аварийный":"· обычный"}</b></div><div class="detail-field"><span>Цикл / пауза по журналу (не простой)</span><b>${o.cycle_minutes==null?"—":`${o.cycle_minutes} мин цикл`} · ${o.paused_minutes} мин пауза</b></div></div>
      <div class="detail-section"><h3>Путь наряда</h3><div style="display:flex;flex-wrap:wrap;gap:5px">${statusFlow}</div></div>
      ${o.reject_reason?`<div class="detail-section"><h3>${o.cancelled_by_master?"Причина отмены":"Причина отказа / доработки"}</h3><p>${ESC(o.reject_reason)}</p></div>`:""}${o.pause_reason?`<div class="detail-section"><h3>Причина паузы</h3><p>${ESC(o.pause_reason)}</p></div>`:""}
      ${o.completion_text?`<div class="detail-section"><h3>Отчёт о выполнении</h3><p>${ESC(o.completion_text)}</p><p style="margin-top:8px">${o.fault_code?`${ESC(o.fault_code.code)} · ${ESC(o.fault_code.label)}`:"Код неисправности не выбран"} · ${o.labor_hours??"—"} ч</p>${materialHTML}</div>`:""}
      <div class="detail-section"><div class="panel-header"><h3>Фото до / после</h3><span class="demo-note">до 5 на фазу · сжатие до 1600 px · EXIF не подтверждает время съёмки</span></div>${files}${uploadAllowed?`<div class="upload-line" style="margin-top:9px"><label class="field-label">Добавить ${phase==="before"?"фото неисправности":"фото после"}<input class="upload-input" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" data-upload-phase="${phase}" multiple></label></div>`:""}</div>
      <div class="detail-section"><h3>Проверка отчёта</h3>${aiBlock}</div>
      <div class="detail-section"><h3>История оборудования · ${ESC(o.equipment.code)}</h3><div class="timeline">${equipHistory}</div></div>
      <div class="detail-section"><h3>История действий</h3><div class="timeline">${timeline||'<p class="demo-note">Пока нет событий. Демозаписи помечены отдельно.</p>'}</div></div>
      ${role()==="master"&&o.status==="issued"?`<div class="action-box"><h3>Переназначить до принятия</h3><div class="field-stack"><label class="field-label">Исполнитель или бригада<select class="field-select" id="reassign-target"><option value="">Выберите исполнителя</option>${(S.data.free_workers||[]).map(w=>`<option value="worker:${w.id}">${ESC(w.username||"worker")} · ${ESC(w.display_name)} · ${ESC(w.availability_label)} · ${w.active_orders||0} актив.</option>`).join("")}<option value="brigade:A">Вся бригада A</option><option value="brigade:B">Вся бригада B</option><option value="brigade:C">Вся бригада C</option></select></label><button class="button button-outline" data-reassign>Сохранить назначение</button></div></div>`:""}
      ${detailButtons(o)?`<div class="action-box"><h3>Следующий шаг</h3><div class="action-buttons">${detailButtons(o)}</div></div>`:""}
      ${role()==="master"&&o.status==="closed"?ratingForm(o):""}
      ${repeatPanel}
      ${role()==="master"&&o.status==="rejected"&&!o.cancelled_by_master?rejectionForm(o):""}
      ${role()==="master"&&["issued","accepted","queued"].includes(o.status)?priorityForm(o):""}
      ${role()==="worker"&&o.status==="in_progress"?completionForm(o):""}
      </div>`;
    bindDrawer(detail);
    const upload=$("[data-upload-phase]");if(upload)upload.disabled=S.uploading.has(`${S.session}:${o.id}:${upload.dataset.uploadPhase}`);
    const completion=$("#save-completion");if(completion)completion.disabled=S.completing.has(`${S.session}:${o.id}`);
  }
  function completionForm(o){
    const codes=S.data.constants.fault_codes.map(c=>`<option value="${c.id}" ${o.fault_code_id===c.id?"selected":""}>${ESC(c.code)} · ${ESC(c.label)}</option>`).join("");
    const first=S.data.constants.materials[0];
    return `<div class="action-box" id="completion-form"><h3>Отчёт о выполнении · обязательно</h3><div class="field-stack"><label class="field-label">Что сделали и каков результат<textarea id="completion-text" class="field-textarea" minlength="20" placeholder="Например: заменили уплотнение, проверили узел; течь не наблюдается.">${ESC(o.completion_text||"")}</textarea></label><div class="field-two"><label class="field-label">Код неисправности<select id="fault-code" class="field-select"><option value="">Выберите</option>${codes}</select></label><label class="field-label">Фактические часы<input id="labor-hours" class="field-input" type="number" min="0.1" max="72" step="0.1" value="${o.labor_hours||1.5}"></label></div><div class="field-label">Использованные материалы и количество <button type="button" class="text-link" id="add-material">＋ Добавить строку</button></div><div id="materials-list"><div class="material-row field-two"><select class="field-select material-id"><option value="">Не использовались</option>${S.data.constants.materials.map(m=>`<option value="${m.id}">${ESC(m.sku)} · ${ESC(m.name)} (${ESC(m.unit)})</option>`).join("")}</select><input class="field-input material-quantity" type="number" min="0.1" step="0.1" value="1"></div></div><label style="font-size:9px;color:#64756e"><input id="materials-not-used" type="checkbox" ${o.materials_not_used?"checked":""}> Материалы не использовались</label><p class="demo-note">Фото можно не прикладывать, чтобы пройти демосценарий ИИ и получить доработку. Мастер не сможет окончательно принять внеплановый наряд без уникального фото «после».</p><button class="button button-primary" id="save-completion">Зафиксировать «Исполнено»</button></div></div>`;
  }
  function ratingForm(o){return `<div class="action-box"><h3>Качество по оценке мастера</h3><label class="field-label">Оценка 1–5 <select class="field-select" id="quality-score"><option value="5" ${o.rating===5?"selected":""}>5 · соответствует</option><option value="4" ${o.rating===4?"selected":""}>4 · небольшое замечание</option><option value="3" ${o.rating===3?"selected":""}>3 · требуется внимание</option><option value="2" ${o.rating===2?"selected":""}>2 · неудовлетворительно</option><option value="1" ${o.rating===1?"selected":""}>1 · не принято</option></select></label><label class="field-label" style="margin-top:8px">Причина корректировки<textarea id="quality-reason" class="field-textarea" placeholder="Обоснование мастера, видно исполнителю">${ESC(o.rating_reason||"")}</textarea></label><label class="field-label" style="margin-top:8px"><input id="repeat-confirmed" type="checkbox" ${o.repeat_confirmed?"checked":""}> Подтвердить повтор той же неисправности на том же оборудовании ≤7 дней</label><button class="button button-soft" style="margin-top:9px" data-save-rating>Сохранить оценку</button><div class="demo-note">Подтверждение проверяется по более раннему закрытому наряду с тем же оборудованием и кодом неисправности. Нужна причина мастера. Отметка относится к этому, более позднему ремонту и сохраняется как факт повтора; без явной причинной связи с предыдущим ремонтом она не снижает оценку исполнителя.</div></div>`;}
  function rejectionForm(o){return `<div class="action-box"><h3>Классификация отказа мастером</h3><label class="field-label"><input id="unjustified-refusal" type="checkbox" ${o.unjustified_refusal?"checked":""}> Отказ признан необоснованным</label><label class="field-label" style="margin-top:8px">Причина решения<textarea id="rejection-reason" class="field-textarea" placeholder="Подтверждение руководителя мастера"></textarea></label><button class="button button-soft" style="margin-top:8px" data-classify-rejection>Сохранить классификацию</button></div>`;}
  function priorityForm(o){return `<div class="action-box"><h3>Приоритет наряда</h3><div class="field-two"><select id="priority-select" class="field-select">${Object.entries({emergency:"Аварийный",high:"Высокий",normal:"Обычный",planned:"Плановый"}).map(([k,v])=>`<option value="${k}" ${o.priority===k?"selected":""}>${v}</option>`).join("")}</select><button class="button button-outline" data-save-priority>Обновить</button></div></div>`;}
  function bindDrawer(detail){
    $("[data-close-drawer]")?.addEventListener("click",closeDrawer);
    $$("[data-action]").forEach(b=>b.addEventListener("click",()=>runAction(b.dataset.action)));
    $$("[data-prompt-action]").forEach(b=>b.addEventListener("click",()=>promptAction(b.dataset.promptAction)));
    $("[data-toggle-completion]")?.addEventListener("click",()=>$("#completion-form")?.scrollIntoView({behavior:"smooth",block:"center"}));
    $("#save-completion")?.addEventListener("click",saveCompletion);
    $("#add-material")?.addEventListener("click",addMaterialRow);
    $("#materials-not-used")?.addEventListener("change",e=>$$('#materials-list select,#materials-list input').forEach(x=>x.disabled=e.target.checked));
    $("[data-upload-phase]")?.addEventListener("change",uploadPhotos);
    $$("[data-reassign]").forEach(b=>b.addEventListener("click",saveAssignment));
    $("[data-save-priority]")?.addEventListener("click",savePriority);
    $("[data-save-rating]")?.addEventListener("click",saveRating);
    $("[data-classify-rejection]")?.addEventListener("click",classifyRejection);
    $("[data-toggle-rating]")?.addEventListener("click",()=>$("#quality-score")?.focus());
  }
  async function updateOrder(endpoint,body,message){
    const c=context();if(!c.orderId||!sameSession(c))return;
    try{
      await api(`/api/orders/${c.orderId}/${endpoint}`,"POST",body);if(!sameSession(c))return;
      if(sameDrawer(c))toast(message);
      await refresh(true);if(sameDrawer(c))await refreshDrawer();
    }catch(e){if(sameDrawer(c))toast(e.message,true);}
  }
  async function runAction(action,payload={}){
    await updateOrder("action",{action,...payload},`Наряд: ${STATUS_RU[actionTarget(action)]||"обновлён"}.`);
  }
  function actionTarget(action){return {accept:"accepted",queue:"queued",start:"in_progress",pause:"paused",resume:"in_progress",complete:"executed",ai_check:"ai_review",close:"closed",request_rework:"rework",reject:"rejected",cancel:"rejected",reissue:"issued"}[action]||action;}
  async function promptAction(action){
    const prompts={reject:"Почему вы отклоняете наряд? Укажите причину.",pause:"Почему работа приостанавливается? Укажите причину.",request_rework:"Какие замечания нужно устранить?",close:"Комментарий мастера к окончательной приёмке. При замечаниях обоснование обязательно.",cancel:"Почему мастер отменяет наряд?"};
    let reason=prompt(prompts[action]||"Причина");if(reason===null)return;
    if(["reject","pause","request_rework","cancel"].includes(action)&&reason.trim().length<4){toast("Причина должна содержать не менее 4 символов.",true);return;}
    await runAction(action,{reason:reason.trim()});
  }
  function addMaterialRow(){
    const wrap=$("#materials-list"), source=$(".material-row",wrap);const clone=source.cloneNode(true);$(".material-id",clone).value="";$(".material-quantity",clone).value="1";wrap.append(clone);
    const remove=document.createElement("button");remove.type="button";remove.className="button button-danger";remove.textContent="Удалить";remove.style.gridColumn="1/-1";remove.addEventListener("click",()=>clone.remove());clone.append(remove);
  }
  async function saveCompletion(){
    const c=context(),key=`${c.session}:${c.orderId}`,button=$("#save-completion");
    if(!c.orderId||!sameSession(c)||S.completing.has(key))return;
    const materials=[];$$('.material-row').forEach(row=>{const id=$(".material-id",row)?.value,qty=$(".material-quantity",row)?.value;if(id)materials.push({material_id:Number(id),quantity:Number(qty)});});
    const data={action:"complete",completion_text:$("#completion-text")?.value.trim(),fault_code_id:Number($("#fault-code")?.value),labor_hours:Number($("#labor-hours")?.value),materials,materials_not_used:$("#materials-not-used")?.checked||false};
    let saved=false;S.completing.add(key);if(button)button.disabled=true;
    try{
      await api(`/api/orders/${c.orderId}/action`,"POST",data);saved=true;if(!sameSession(c))return;
      if(sameDrawer(c))toast("Отчёт зафиксирован. Запускаем обязательную проверку…");
      const checked=await api(`/api/orders/${c.orderId}/action`,"POST",{action:"ai_check"});if(!sameSession(c))return;
      if(sameDrawer(c))toast(checked.order.status==="rework"?"ИИ-проверка направила наряд на доработку.":"Проверка завершена; решение остаётся за мастером.");
      await refresh(true);if(sameDrawer(c))await refreshDrawer();
    }catch(e){
      if(!sameSession(c))return;
      if(sameDrawer(c))toast(saved?`Отчёт сохранён, но проверка не завершена: ${e.message}. Откройте наряд и повторите проверку.`:`Не удалось подтвердить сохранение отчёта: ${e.message}`,true);
      // A rejected completion must leave the user's draft intact for correction.
      if(saved){await refresh(true);if(sameDrawer(c))await refreshDrawer();}
    }finally{
      S.completing.delete(key);if(button)button.disabled=false;
      if(sameDrawer(c)){const current=$("#save-completion");if(current)current.disabled=false;}
    }
  }
  async function saveAssignment(){
    const value=$("#reassign-target")?.value;if(!value){toast("Выберите исполнителя или бригаду.",true);return;}
    const [kind,id]=value.split(":");const body=kind==="brigade"?{brigade:id}:{worker_id:Number(id)};
    await updateOrder("assign",body,"Назначение обновлено.");
  }
  async function savePriority(){await updateOrder("priority",{priority:$("#priority-select").value},"Приоритет обновлён.");}
  async function saveRating(){
    const reason=$("#quality-reason")?.value.trim();if(!reason||reason.length<4){toast("Укажите основание оценки мастера.",true);return;}
    await updateOrder("rating",{rating:Number($("#quality-score").value),reason},"Оценка мастера сохранена в аудите.");
  }
  async function createRepeatLink(){
    const c=context(),previous_order_id=Number($("#repeat-previous")?.value),reason=$("#repeat-reason")?.value.trim();
    if(!previous_order_id||!reason||reason.length<4){toast("Выберите предыдущий наряд и укажите основание.",true);return;}
    try{await api(`/api/orders/${c.orderId}/repeat-link`,"POST",{previous_order_id,reason});if(!sameDrawer(c))return;toast("Связь повтора сохранена в аудите; фактор пересчитан по ручной атрибуции.");await refresh(true);if(sameDrawer(c))await refreshDrawer();}catch(e){if(sameDrawer(c))toast(e.message,true);}
  }
  async function revokeRepeatLink(){
    const c=context(),reason=$("#repeat-revoke-reason")?.value.trim();
    if(!reason||reason.length<4){toast("Укажите основание отмены связи.",true);return;}
    try{await api(`/api/orders/${c.orderId}/repeat-link/revoke`,"POST",{reason});if(!sameDrawer(c))return;toast("Связь отменена; рейтинг пересчитан без неё.");await refresh(true);if(sameDrawer(c))await refreshDrawer();}catch(e){if(sameDrawer(c))toast(e.message,true);}
  }
  async function classifyRejection(){
    const reason=$("#rejection-reason")?.value.trim();if(!reason||reason.length<4){toast("Укажите причину решения мастера.",true);return;}
    await updateOrder("rating",{unjustified_refusal:$("#unjustified-refusal").checked,reason},"Классификация отказа сохранена.");
  }
  function exifPayload(bytes,type){
    const ascii=(b,start,length)=>String.fromCharCode(...b.slice(start,start+length));
    const hasExif=(b,start)=>b.length>=start+6&&ascii(b,start,6)==="Exif\0\0";
    const withHeader=data=>{if(hasExif(data,0))return data;const out=new Uint8Array(data.length+6);out.set([69,120,105,102,0,0]);out.set(data,6);return out;};
    if(type==="image/jpeg"){
      let p=2;while(p+4<bytes.length&&bytes[p]===255){const marker=bytes[p+1];if(marker===218||marker===217)break;const length=bytes[p+2]*256+bytes[p+3];if(length<2||p+2+length>bytes.length)break;if(marker===225&&hasExif(bytes,p+4))return bytes.slice(p+4,p+2+length);p+=2+length;}
    }else if(type==="image/png"){
      let p=8;while(p+12<=bytes.length){const length=bytes[p]*0x1000000+bytes[p+1]*65536+bytes[p+2]*256+bytes[p+3];if(length<0||p+12+length>bytes.length)break;if(ascii(bytes,p+4,4)==="eXIf"){const data=bytes.slice(p+8,p+8+length);return withHeader(data);}p+=12+length;if(ascii(bytes,p-8,4)==="IEND")break;}
    }else if(type==="image/webp"&&ascii(bytes,0,4)==="RIFF"){
      let p=12;while(p+8<=bytes.length){const size=bytes[p+4]|bytes[p+5]<<8|bytes[p+6]<<16|bytes[p+7]<<24;if(size<0||p+8+size>bytes.length)break;if(ascii(bytes,p,4)==="EXIF"){const data=bytes.slice(p+8,p+8+size);return withHeader(data);}p+=8+size+(size&1);}
    }
    return null;
  }
  function insertJpegExif(jpeg,exif){
    if(!exif||exif.length+2>65535||jpeg.length<2||jpeg[0]!==255||jpeg[1]!==216)return {bytes:jpeg,preserved:false};
    const out=new Uint8Array(jpeg.length+exif.length+4);out.set([255,216,255,225,(exif.length+2)>>8,(exif.length+2)&255],0);out.set(exif,6);out.set(jpeg.slice(2),6+exif.length);return {bytes:out,preserved:true};
  }
  async function compressImage(file){
    if(!["image/jpeg","image/png","image/webp"].includes(file.type.toLowerCase()))throw new Error("Выберите JPEG, PNG или WebP.");
    if(file.size>50_000_000)throw new Error("Исходное фото больше 50 МБ.");
    let bitmap=null,url=null;
    try{if(typeof createImageBitmap==="function")bitmap=await createImageBitmap(file,{imageOrientation:"none"});}catch{}
    if(!bitmap){url=URL.createObjectURL(file);bitmap=await new Promise((resolve,reject)=>{const img=new Image();img.onload=()=>resolve(img);img.onerror=reject;img.src=url;});}
    const scale=Math.min(1,1600/Math.max(bitmap.width,bitmap.height)),canvas=document.createElement("canvas");canvas.width=Math.max(1,Math.round(bitmap.width*scale));canvas.height=Math.max(1,Math.round(bitmap.height*scale));
    const ctx=canvas.getContext("2d");if(!ctx)throw new Error("Браузер не смог подготовить фото.");ctx.drawImage(bitmap,0,0,canvas.width,canvas.height);bitmap.close?.();if(url)URL.revokeObjectURL(url);
    const blob=await new Promise(resolve=>canvas.toBlob(resolve,"image/jpeg",.82));if(!blob)throw new Error("Не удалось сжать фото.");
    let bytes=new Uint8Array(await blob.arrayBuffer()),exif=null,preserved=false;
    if(typeof createImageBitmap==="function")try{exif=exifPayload(new Uint8Array(await file.arrayBuffer()),file.type.toLowerCase());const inserted=insertJpegExif(bytes,exif);bytes=inserted.bytes;preserved=inserted.preserved;}catch{}
    if(bytes.length>4_000_000)throw new Error("Фото после сжатия всё ещё больше 4 МБ; попробуйте уменьшить разрешение камеры.");
    const compressed=new Blob([bytes],{type:"image/jpeg"});const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(compressed);});
    const stem=file.name.replace(/\.[^.]+$/,"")||"photo";
    return {data_url:data,file_name:`${stem}.jpg`,client_compressed:true,source_size_bytes:file.size,source_media_type:file.type,exif_transfer_succeeded:preserved};
  }
  async function uploadPhotos(e){
    const c=context(),input=e.currentTarget,phase=input.dataset.uploadPhase,files=[...input.files||[]];
    const key=`${c.session}:${c.orderId}:${phase}`;
    if(!files.length||!c.orderId||!sameSession(c)||S.uploading.has(key))return;
    if(files.length+$$('.photo-item').filter(p=>p.dataset.phase===phase).length>5){toast("Допустимо не более пяти фото для каждой фазы «до» и «после».",true);input.value="";return;}
    const started=performance.now();input.disabled=true;S.uploading.add(key);
    try{
      for(const file of files){
        const payload=await compressImage(file);if(!sameSession(c))return;
        await api(`/api/orders/${c.orderId}/photos`,"POST",{...payload,phase});if(!sameSession(c))return;
      }
      const elapsed=((performance.now()-started)/1000).toFixed(1);if(sameDrawer(c))toast(`Фото загружено за ${elapsed} с. Дата загрузки не подтверждает свежесть съёмки.`);
    }catch(err){if(sameDrawer(c))toast(err.message,true);}
    finally{
      S.uploading.delete(key);input.disabled=false;input.value="";
      // Reconcile successful partial uploads too, without clearing a completion draft.
      if(sameDrawer(c))await refreshDrawer(true);
    }
  }

  function openNewOrder(){
    if(role()!=="master")return;
    S.drawerVersion++;S.orderId=null;S.drawerOrderId=null;S.drawerStatus=null;
    const areas=S.data.constants.areas,equipment=S.data.constants.equipment;
    const eqOpts=equipment.map(e=>`<option value="${e.id}" data-area="${e.area_id}">${ESC(e.code)} · ${ESC(e.name)}</option>`).join("");
    const workers=S.data.free_workers||[];
    $("#detail-drawer").innerHTML=`<div class="drawer-head"><div><small>МАСТЕР · ВЫДАЧА</small><b>Новый наряд</b></div><button class="drawer-close" data-close-drawer>×</button></div><div class="drawer-body"><h1 class="detail-title">Выдать работу</h1><p class="detail-sub">Форма сохраняет наряд сразу в серверную базу и журнал. Выберите исполнителя со статусом загрузки или бригаду.</p><div class="action-box"><div class="field-stack">
      <label class="field-label">Типовой шаблон<select id="issue-template" class="field-select"><option value="">Свободное описание</option><option value="pump">Насос · вибрация</option><option value="belt">Конвейер · проскальзывание</option><option value="fan">Вентилятор · шум</option><option value="pm">Плановый осмотр</option></select></label>
      <label class="field-label">Название наряда<input id="issue-title" class="field-input" minlength="4" placeholder="Кратко: что произошло"></label>
      <label class="field-label">Описание проблемы<textarea id="issue-description" class="field-textarea" minlength="10" placeholder="Опишите наблюдение и требуемую работу"></textarea></label>
      <div class="field-two"><label class="field-label">Тип работы<select id="issue-type" class="field-select"><option value="unscheduled">Внеплановый / аварийный</option><option value="planned">Плановый</option></select></label><label class="field-label">Приоритет<select id="issue-priority" class="field-select"><option value="emergency">Аварийный · срочно</option><option value="high">Высокий</option><option value="normal" selected>Обычный</option><option value="planned">Плановый</option></select></label></div>
      <label class="field-label">Участок<select id="issue-area" class="field-select"><option value="">Выберите участок</option>${areas.map(a=>`<option value="${a.id}">${ESC(a.name)}</option>`).join("")}</select></label>
      <label class="field-label">Оборудование<select id="issue-equipment" class="field-select"><option value="">Выберите оборудование</option>${eqOpts}</select></label>
      <label class="field-label">Исполнитель или бригада<select id="issue-assignee" class="field-select"><option value="">Выберите по загрузке</option>${workers.map(w=>`<option value="worker:${w.id}">${ESC(w.username||"worker")} · ${ESC(w.display_name)} · ${ESC(w.availability_label)} · ${w.active_orders||0} активных · рейтинг ${w.rating_detail?.score??"—"}</option>`).join("")}<option value="brigade:A">Бригада A · выбрать наименее занятого</option><option value="brigade:B">Бригада B · выбрать наименее занятого</option><option value="brigade:C">Бригада C · выбрать наименее занятого</option></select></label>
      <div class="field-two"><label class="field-label">Норматив срока, часы<input id="issue-hours" class="field-input" type="number" min="0.5" max="720" step="0.5" value="8"></label><label class="field-label">Напоминание<input class="field-input" value="За 30 мин · настройка сервера" disabled></label></div>
      <p class="demo-note">До пяти фото «до» можно добавить после выдачи в карточке наряда. Норматив срока от даты выдачи; фактическое расписание смены не задано.</p>
      <button class="button button-primary" id="issue-submit">Выдать наряд</button><div class="demo-note">Быстрая выдача по типу/шаблону: цель ≤1 мин и ≤6 нажатий при выборе исполнителя, шаблона и норматива. Измерение зависит от ввода оператора и не считается доказанным SLA.</div></div></div></div>`;
    $("#drawer-backdrop").classList.remove("hidden");$("#detail-drawer").classList.add("open");$("#detail-drawer").setAttribute("aria-hidden","false");
    bindIssueForm();$("#issue-submit").disabled=S.creatingOrder;$("[data-close-drawer]")?.addEventListener("click",closeDrawer);
  }
  function bindIssueForm(){
    const area=$("#issue-area"), equipment=$("#issue-equipment");
    const filterEquipment=()=>{const id=area.value;[...equipment.options].forEach(op=>{if(!op.value)return;const match=op.dataset.area===id;op.hidden=!!id&&!match;if(!match&&op.selected)equipment.value="";});};area.addEventListener("change",filterEquipment);
    $("#issue-template").addEventListener("change",e=>{
      const templates={pump:{title:"Повторная вибрация насосного узла",description:"Наблюдается вибрация насосного узла. Осмотреть крепления и подшипниковую опору, зафиксировать результат проверки.",code:"EQ-003",type:"unscheduled",priority:"high"},belt:{title:"Проскальзывание конвейерной ленты",description:"Лента проскальзывает при работе. Проверить натяжение и ролики, описать выполненную регулировку и результат.",code:"EQ-002",type:"unscheduled",priority:"high"},fan:{title:"Шум вентиляционного подшипника",description:"Появился шум в вентиляционном узле. Осмотреть подшипник и зафиксировать наблюдаемый результат.",code:"EQ-005",type:"unscheduled",priority:"normal"},pm:{title:"Плановый осмотр перед сменой",description:"Провести плановый осмотр узла и записать состояние оборудования и выполненные работы.",code:"EQ-004",type:"planned",priority:"planned"}};
      const t=templates[e.target.value];if(!t)return;$("#issue-title").value=t.title;$("#issue-description").value=t.description;$("#issue-type").value=t.type;$("#issue-priority").value=t.priority;const eq=[...equipment.options].find(o=>o.textContent.includes(t.code));if(eq){equipment.value=eq.value;area.value=eq.dataset.area;filterEquipment();equipment.value=eq.value;}
    });
    $("#issue-submit").addEventListener("click",createOrder);
  }
  async function createOrder(){
    const c=context(),button=$("#issue-submit");if(!sameSession(c)||S.creatingOrder||!button)return;
    const target=$("#issue-assignee").value;if(!target){toast("Выберите исполнителя или бригаду.",true);return;}
    const [kind,value]=target.split(":");const payload={title:$("#issue-title").value.trim(),description:$("#issue-description").value.trim(),work_type:$("#issue-type").value,priority:$("#issue-priority").value,area_id:Number($("#issue-area").value),equipment_id:Number($("#issue-equipment").value),norm_hours:Number($("#issue-hours").value),...(kind==="worker"?{worker_id:Number(value)}:{brigade:value})};
    S.creatingOrder=true;button.disabled=true;
    try{
      const result=await api("/api/orders","POST",payload);if(!sameSession(c))return;
      toast(`Выдан наряд ${result.order.code}.`);
      if(sameDrawer(c))await openOrder(result.order.id);
      await refresh(true);
    }catch(e){if(sameSession(c))toast(e.message,true);}
    finally{
      if(sameSession(c)){S.creatingOrder=false;const current=$("#issue-submit");if(current)current.disabled=false;}
      button.disabled=false;
    }
  }

  function bindGlobal(){
    $("#login-form").addEventListener("submit",login);
    $("#demo-account").addEventListener("change",e=>{$("#username").value=e.target.value;});
    $("#logout").addEventListener("click",()=>{const request=api("/api/logout","POST",{});logoutLocal();request.catch(()=>{});});
    $("#mobile-menu").addEventListener("click",()=>$("#sidebar").classList.toggle("mobile-open"));
    $("#drawer-backdrop").addEventListener("click",closeDrawer);
    $("#banner-dismiss").addEventListener("click",()=>$(".synthetic-banner").remove());
    $("#notification-button").addEventListener("click",showNotifications);
    window.addEventListener("online",()=>{$("#offline-banner").classList.add("hidden");refresh();});window.addEventListener("offline",()=>$("#offline-banner").classList.remove("hidden"));
    $$(".nav-item").forEach(b=>b.addEventListener("click",()=>navigate(b.dataset.view)));
    window.addEventListener("beforeinstallprompt",e=>{e.preventDefault();S.installPrompt=e;$("#install-button").classList.remove("hidden");});
    $("#install-button").addEventListener("click",async()=>{if(!S.installPrompt)return;S.installPrompt.prompt();await S.installPrompt.userChoice;S.installPrompt=null;$("#install-button").classList.add("hidden");});
  }
  function showNotifications(){
    let node=$("#notification-popover");if(node){node.remove();return;}
    node=document.createElement("div");node.id="notification-popover";node.className="notification-popover";const list=S.data?.notifications||[];
    node.innerHTML=`<h3>Уведомления</h3>${list.map(n=>`<div class="notification-item">${ESC(n.message)}<small>${ESC(n.order_code||"Система")} · ${dateFmt(n.created_at)}</small></div>`).join("")||'<div class="empty-state">Новых уведомлений нет.</div>'}`;document.body.append(node);
    if(list.length)api("/api/notifications/read","POST",{}).then(()=>refresh(true)).catch(()=>{});
    setTimeout(()=>{document.addEventListener("click",function outside(e){if(!node.contains(e.target)&&!$("#notification-button").contains(e.target)){node.remove();document.removeEventListener("click",outside);}}, {once:true});},0);
  }

  bindGlobal();
  api("/api/me").then(data=>{S.me=data.user;startApp();}).catch(()=>{});
})();
