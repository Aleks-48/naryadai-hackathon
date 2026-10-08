/* Focused browser-logic regressions, without dependencies or a live service.
 * Run: node --test tests/test_frontend_races.js
 * To reproduce against a reference: NARYADAI_APP_JS=/path/to/app.js node --test ...
 * The VM exposes closure functions in this test only; production has no test API.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const sourcePath = process.env.NARYADAI_APP_JS || path.join(__dirname, '../static/app.js');
const deferred = () => {let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};};
const flush = () => new Promise(resolve => setImmediate(resolve));
function element(value='') {
  const classes=new Set();
  return {value,disabled:false,checked:false,dataset:{},options:[],children:[],events:{},attrs:{},controls:new Map(),innerHTML:'',textContent:'',id:'',scrollTop:0,isConnected:true,parentElement:null,
    classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),toggle:(x,v)=>{if(v===undefined)v=!classes.has(x);v?classes.add(x):classes.delete(x)},contains:x=>classes.has(x)},
    addEventListener(name,fn){this.events[name]=fn},setAttribute(k,v){this.attrs[k]=v},
    append(node){this.children.push(node);node.parentElement=this;node.isConnected=true},remove(){this.isConnected=false;if(this.parentElement)this.parentElement.children=this.parentElement.children.filter(x=>x!==this)},focus(){this.focused=true},
    contains(node){return this===node||this.children.includes(node)},querySelector(selector){if(!this.innerHTML.includes(selector.replace(/[\[\]]/g,'').split('=')[0]))return null;if(!this.controls.has(selector))this.controls.set(selector,element());return this.controls.get(selector)},querySelectorAll(){return []}};
}
function harness() {
  const nodes=new Map(), groups=new Map();
  const get=selector=>{if(!nodes.has(selector))nodes.set(selector,element());return nodes.get(selector)};
  const documentListeners=new Map(),body=element();
  const document={activeElement:null,body,querySelector:s=>{const direct=nodes.get(s);if(direct?.isConnected)return direct;if(s.startsWith('#'))return body.children.find(n=>n.id===s.slice(1)&&n.isConnected)||null;return null},querySelectorAll:s=>groups.get(s)||[],createElement:()=>element(),addEventListener(name,fn){documentListeners.set(name,fn)},removeEventListener(name,fn){if(documentListeners.get(name)===fn)documentListeners.delete(name)}};
  ['#app','#login-screen','#detail-drawer','#drawer-backdrop','#view-root','#toast-region','#offline-banner','#telegram-button'].forEach(get);
  const localStorageWrites=[],logs=[];
  const globals={document,console:{log:(...x)=>logs.push(x),warn:(...x)=>logs.push(x),error:(...x)=>logs.push(x)},localStorage:{setItem:(...x)=>localStorageWrites.push(x),removeItem:(...x)=>localStorageWrites.push(x),getItem:()=>null},navigator:{onLine:true},location:{protocol:'http:',hostname:'example.invalid'},window:{addEventListener(){}},URLSearchParams,setTimeout:()=>0,clearInterval(){},setInterval:()=>1,performance:{now:()=>0},fetch:()=>Promise.reject(new Error('Unexpected real fetch')),FileReader:class{},prompt:()=>null,confirm:()=>true};
  const names=['api','logoutLocal','refresh','refreshDrawer','openOrder','openNewOrder','closeDrawer','saveCompletion','uploadPhotos','createOrder','bindIssueForm','renderDrawer','detailButtons','reassignmentForm','bindDrawer','loadReport','renderReports','bindReportControls','renderReportResult','reportEquipmentOptions','downtimeOrderOptions','submitEquipmentDowntime','loadAudit','render','runAction','showTelegram','moveWorkQueue','exifPayload','insertJpegExif'];
  const expose=`globalThis.app={S,${names.join(',')},override(overrides){${['api','refresh','refreshDrawer','openOrder','renderDrawer','render','syncChrome','compressImage','renderReportResult'].map(n=>`if(overrides.${n})${n}=overrides.${n};`).join('')}}};`;
  const source=fs.readFileSync(sourcePath,'utf8').replace(/\n  bindGlobal\(\);[\s\S]*?\n\}\)\(\);\s*$/,`\n  ${expose}\n})();`);
  vm.runInNewContext(source,globals,{filename:sourcePath});
  const {app}=globals;
  app.S.me={id:1,role:'worker',csrf:'test'};
  app.S.orderId=101;
  app.S.data={constants:{areas:[],equipment:[],users:[],fault_codes:[],materials:[]},free_workers:[]};
  app.override({syncChrome(){}});
  return {app,get,nodes,groups,document,globals,localStorageWrites,logs,documentListeners};
}
function completionInputs(h) {
  h.get('#completion-text').value='Заменили уплотнение и проверили результат';
  h.get('#worker-completion-comment').value='Дополнительная заметка исполнителя';
  h.get('#fault-code').value='2';h.get('#labor-hours').value='1.5';h.get('#materials-not-used').checked=true;h.get('#save-completion');
}
function issueInputs(h) {
  h.app.S.me.role='master';
  for(const [id,value] of Object.entries({'issue-assignee':'worker:2','issue-title':'Новый наряд','issue-description':'Подробное описание работы','issue-type':'planned','issue-priority':'normal','issue-area':'1','issue-equipment':'3','issue-hours':'8','issue-template':'pump','issue-before-photos':'','issue-submit':''}))h.get('#'+id).value=value;
}

test('EXIF transfer survives browser JPEG recompression and can be inspected again',()=>{
  const h=harness();
  const exif=Uint8Array.from([69,120,105,102,0,0,73,73,42,0,8,0]);
  const length=exif.length+2;
  const original=Uint8Array.from([255,216,255,225,length>>8,length&255,...exif,255,217]);
  const found=h.app.exifPayload(original,'image/jpeg');
  assert.deepEqual(Array.from(found),Array.from(exif));
  const compressed=Uint8Array.from([255,216,17,18,19,255,217]);
  const result=h.app.insertJpegExif(compressed,found);
  assert.equal(result.preserved,true);
  assert.deepEqual(Array.from(h.app.exifPayload(result.bytes,'image/jpeg')),Array.from(exif));
  assert.equal(h.app.insertJpegExif(compressed,null).preserved,false);
});

test('completion and mandatory check stay on initiating order after navigation',async()=>{
  const h=harness();completionInputs(h);const pending=deferred(),calls=[];
  h.app.override({api:async(p,m,b)=>{calls.push([p,b]);if(b?.action==='complete')await pending.promise;return {order:{status:'ai_review'}}},refresh:async()=>{},renderDrawer(){}});
  const save=h.app.saveCompletion();h.app.S.orderId=202;pending.resolve();await save;
  assert.deepEqual(calls.map(c=>c[0]),['/api/orders/101/action','/api/orders/101/action']);
  assert.equal(calls[0][1].worker_completion_comment,'Дополнительная заметка исполнителя');
});

test('completion is single-flight and failed validation keeps the draft',async()=>{
  const h=harness();completionInputs(h);const pending=deferred();let requests=0,refreshes=0;
  h.app.override({api:async()=>{requests++;await pending.promise;throw new Error('Validation')},refresh:async()=>{refreshes++}});
  const first=h.app.saveCompletion(),second=h.app.saveCompletion();assert.equal(h.get('#save-completion').disabled,true);
  pending.resolve();await Promise.all([first,second]);assert.equal(requests,1);assert.equal(refreshes,0);assert.equal(h.get('#save-completion').disabled,false);assert.match(h.get('#completion-text').value,/уплотнение/);
});

test('logout between completion and AI check stops the follow-up write',async()=>{
  const h=harness();completionInputs(h);const pending=deferred(),calls=[];
  h.app.override({api:async(p)=>{calls.push(p);await pending.promise;return {order:{status:'executed'}}},refresh:async()=>{}});
  const saving=h.app.saveCompletion();h.app.logoutLocal();pending.resolve();await saving;assert.equal(calls.length,1);assert.equal(h.app.S.me,null);
});

test('photos stay on initiating order across FileReader and upload awaits',async()=>{
  const h=harness(),read=deferred(),uploaded=deferred(),calls=[];let reads=0;
  h.app.override({compressImage:async file=>{if(++reads===1)await read.promise;return {file_name:file.name,data_url:'data:image/png;base64,AA=='}},api:async(p,m,b)=>{calls.push([p,b]);if(calls.length===1)await uploaded.promise},renderDrawer(){}});
  const input=element();input.dataset.uploadPhase='after';input.files=[{name:'one.png'},{name:'two.png'}];
  const task=h.app.uploadPhotos({currentTarget:input});h.app.S.orderId=202;read.resolve();await flush();h.app.S.orderId=303;uploaded.resolve();await task;
  assert.deepEqual(calls.map(c=>c[0]),['/api/orders/101/photos','/api/orders/101/photos']);assert.equal(input.disabled,false);
});

test('logout during image reading prevents photo transmission',async()=>{
  const h=harness(),read=deferred();let writes=0;
  h.app.override({compressImage:()=>read.promise,api:async()=>{writes++}});
  const input=element();input.dataset.uploadPhase='after';input.files=[{name:'one.png'}];
  const task=h.app.uploadPhotos({currentTarget:input});h.app.logoutLocal();read.resolve({data_url:'image'});await task;assert.equal(writes,0);
});

test('five before photos do not consume the separate after-photo allowance',async()=>{
  const h=harness();let writes=0;h.groups.set('.photo-item',Array.from({length:5},()=>({dataset:{phase:'before'}})));
  h.app.override({compressImage:async()=>({data_url:'image'}),api:async(p)=>{if(p.endsWith('/photos'))writes++;return {order:{status:'in_progress'}}},renderDrawer(){}});
  const input=element();input.dataset.uploadPhase='after';input.files=[{name:'one.png'}];await h.app.uploadPhotos({currentTarget:input});assert.equal(writes,1);
});

test('six photos within one phase are rejected before reading files',async()=>{
  const h=harness();h.groups.set('.photo-item',Array.from({length:5},()=>({dataset:{phase:'after'}})));let reads=0;
  h.app.override({compressImage:async()=>{reads++}});const input=element();input.dataset.uploadPhase='after';input.files=[{name:'six.png'}];await h.app.uploadPhotos({currentTarget:input});assert.equal(reads,0);
});

test('late drawer response cannot replace a newer order',async()=>{
  const h=harness(),first=deferred(),renders=[];
  h.app.override({api:p=>p.endsWith('/101')?first.promise:Promise.resolve({order:{id:202,status:'issued'}}),renderDrawer:d=>renders.push(d.order.id)});
  const old=h.app.openOrder(101);await h.app.openOrder(202);first.resolve({order:{id:101,status:'issued'}});await old;assert.deepEqual(renders,[202]);
});

test('late drawer error does not overwrite a new form',async()=>{
  const h=harness(),pending=deferred();issueInputs(h);h.app.override({api:()=>pending.promise});
  const old=h.app.openOrder(101);h.app.openNewOrder();const form=h.get('#detail-drawer').innerHTML;pending.reject(new Error('Old failure'));await old;
  assert.equal(h.app.S.orderId,null);assert.equal(h.get('#detail-drawer').innerHTML,form);
});

test('template finds equipment options and its matching area',()=>{
  const h=harness();issueInputs(h);const option={value:'3',textContent:'EQ-003 · Насос',dataset:{area:'2'},selected:false};h.get('#issue-equipment').options=[option];
  h.app.bindIssueForm();h.get('#issue-template').events.change({target:{value:'pump'}});assert.equal(h.get('#issue-equipment').value,'3');assert.equal(h.get('#issue-area').value,'2');
});

test('issued work does not require a pre-work photo in the creation form',async()=>{
  const h=harness();issueInputs(h);h.get('#issue-type').value='unscheduled';const calls=[];
  h.app.override({api:async(p,m,b)=>{calls.push([p,m,b]);return {order:{id:9,code:'DEMO-9'}}},openOrder:async()=>{},refresh:async()=>{}});
  await h.app.createOrder();assert.equal(calls.length,1);assert.equal(calls[0][0],'/api/orders');
  assert.equal(Object.hasOwn(calls[0][2],'before_photo'),false);
  assert.equal(Object.hasOwn(calls[0][2],'before_photos'),false);
});

test('issue creation sends zero, one, or five optional photos and rejects six before compression',async()=>{
  for(const count of [0,1,5,6]){
    const h=harness();issueInputs(h);const input=h.get('#issue-before-photos');
    input.files=Array.from({length:count},(_,i)=>({name:`before-${i}.jpg`}));
    const calls=[];let compressed=0;
    h.app.override({compressImage:async file=>{compressed++;return {file_name:file.name,data_url:'data:image/jpeg;base64,AA=='}},
      api:async(p,m,b)=>{calls.push([p,m,b]);return {order:{id:9,code:'DEMO-9'}}},openOrder:async()=>{},refresh:async()=>{}});
    await h.app.createOrder();
    if(count<=5){
      assert.equal(calls.length,1);assert.equal(calls[0][0],'/api/orders');
      assert.equal(calls[0][2].before_photos?.length||0,count);assert.equal(compressed,count);
    }else{assert.equal(calls.length,0);assert.equal(compressed,0);}
  }
});

test('photo chooser supports camera or gallery without forcing capture',()=>{
  const source=fs.readFileSync(sourcePath,'utf8');
  assert.match(source,/id="issue-before-photos" type="file"[^>]*multiple/);
  assert.doesNotMatch(source,/capture="environment"/);
  assert.ok(source.includes('data-upload-phase=\"${phase}\" multiple'));
  assert.ok(source.includes('current-shift-focus'));
  assert.ok(source.includes('\u041e\u0447\u0435\u0440\u0435\u0434\u044c \u0438 \u043f\u0440\u0438\u0451\u043c\u043a\u0430'));
});

test('duplicate photo rows do not use the remaining unique-photo quota',async()=>{
  const h=harness(),calls=[];
  h.groups.set('.photo-item',Array.from({length:5},(_,i)=>({dataset:{phase:'after',duplicate:i===0?'0':'1'}})));
  h.app.override({compressImage:async file=>({file_name:file.name,data_url:'data:image/jpeg;base64,AA=='}),
    api:async(p,m,b)=>{calls.push([p,m,b]);return {photo:{id:99}}},refreshDrawer:async()=>{}});
  const input=element();input.dataset.uploadPhase='after';input.files=[{name:'replacement.jpg'}];
  await h.app.uploadPhotos({currentTarget:input});
  assert.equal(calls.length,1);assert.equal(calls[0][0],'/api/orders/101/photos');
});

test('unscheduled orders can be accepted without a unique pre-work photo',()=>{
  const h=harness(),order={status:'issued',work_type:'unscheduled',photos:[]};
  assert.match(h.app.detailButtons(order),/data-action="accept"/);
  assert.doesNotMatch(h.app.detailButtons(order),/data-action="accept" disabled/);
  const queued=h.app.detailButtons({...order,status:'queued'});
  assert.match(queued,/data-action="accept"/);assert.doesNotMatch(queued,/data-action="accept" disabled/);
  h.app.S.me.role='worker';
  assert.doesNotMatch(h.app.detailButtons({...order,work_type:'planned'}),/data-action="accept" disabled/);
});

test('rejected master detail offers a worker or brigade selector for reassignment',()=>{
  const h=harness();h.app.S.me.role='master';h.app.S.data.free_workers=[{id:12,username:'worker12',display_name:'Synthetic Worker',availability_label:'Свободен',active_orders:0}];
  const html=h.app.reassignmentForm({status:'rejected',cancelled_by_master:false});
  assert.match(html,/<select[^>]+id="reassign-target"/);
  assert.match(html,/value="worker:12"/);
  for(const brigade of ['A','B','C'])assert.match(html,new RegExp(`value="brigade:${brigade}"`));
  assert.match(html,/data-reassign/);
});

test('reassignment binding preserves its initiating order and prevents double submission',async()=>{
  const h=harness(),button=element(),pending=deferred(),calls=[];button.dataset={};h.groups.set('[data-reassign]',[button]);
  h.app.S.me.role='master';h.app.S.orderId=101;h.get('#reassign-target').value='worker:12';h.app.bindDrawer({});
  h.app.override({api:(path,method,body)=>{calls.push([path,method,body]);return pending.promise},refresh:async()=>{},refreshDrawer:async()=>{}});
  const first=button.events.click({currentTarget:button}),again=button.events.click({currentTarget:button});
  assert.equal(calls.length,1);assert.equal(button.disabled,true);
  const reopenedButton=element();h.nodes.set('[data-reassign]',reopenedButton);h.app.S.drawerVersion++;reopenedButton.disabled=true;
  pending.resolve({ok:true});await Promise.all([first,again]);
  assert.equal(calls.length,1);assert.equal(calls[0][0],'/api/orders/101/assign');assert.equal(calls[0][1],'POST');assert.equal(calls[0][2].worker_id,12);
  assert.equal(h.app.S.orderId,101);assert.equal(reopenedButton.disabled,false);
});

test('repeat-link controls are bound, single-flight, and discard stale completion',async()=>{
  const h=harness(),create=element(),revoke=element(),pending=deferred(),calls=[];h.nodes.set('[data-create-repeat]',create);h.nodes.set('[data-revoke-repeat]',revoke);
  h.app.S.me.role='master';h.app.S.orderId=101;h.get('#repeat-previous').value='88';h.get('#repeat-reason').value='Same fault confirmed by the master';h.get('#repeat-revoke-reason').value='Manual attribution corrected';h.app.bindDrawer({});
  let refreshes=0;h.app.override({api:(path,method,body)=>{calls.push([path,method,body]);return pending.promise},refresh:async()=>{refreshes++},refreshDrawer:async()=>{}});
  const first=create.events.click({currentTarget:create}),again=create.events.click({currentTarget:create});
  assert.equal(calls.length,1);assert.equal(create.disabled,true);
  h.app.S.orderId=303;pending.resolve({ok:true});await Promise.all([first,again]);
  assert.equal(calls[0][0],'/api/orders/101/repeat-link');assert.equal(refreshes,0);

  const h2=harness(),create2=element(),revoke2=element();h2.nodes.set('[data-create-repeat]',create2);h2.nodes.set('[data-revoke-repeat]',revoke2);h2.app.S.me.role='master';h2.app.S.orderId=202;
  h2.get('#repeat-revoke-reason').value='Manual attribution corrected';h2.app.bindDrawer({});let revokeCalls=0;
  h2.app.override({api:async(path)=>{if(path.endsWith('/revoke'))revokeCalls++;return {ok:true}},refresh:async()=>{},refreshDrawer:async()=>{}});
  h2.globals.confirm=()=>false;await revoke2.events.click({currentTarget:revoke2});assert.equal(revokeCalls,0);
  h2.globals.confirm=()=>true;await revoke2.events.click({currentTarget:revoke2});assert.equal(revokeCalls,1);
});

test('issuance ignores repeated submit and does not reopen after cancellation',async()=>{
  const h=harness();issueInputs(h);h.app.S.orderId=null;const pending=deferred();let writes=0;
  h.app.override({api:async()=>{writes++;return pending.promise},refresh:async()=>{}});
  const first=h.app.createOrder(),again=h.app.createOrder();assert.equal(h.get('#issue-submit').disabled,true);h.app.closeDrawer();pending.resolve({order:{id:900,code:'N-900'}});await Promise.all([first,again]);
  assert.equal(writes,1);assert.equal(h.app.S.orderId,null);assert.equal(h.get('#detail-drawer').classList.contains('open'),false);
});

test('bootstrap polling preserves report results and report filter DOM',async()=>{
  const h=harness();h.app.S.view='reports';h.get('#report-result').innerHTML='report result';h.get('#report-date').value='2026-09-15';h.app.S.orderId=null;let renders=0;
  h.app.override({api:async()=>({user:h.app.S.me}),render(){renders++;h.get('#report-result').innerHTML='reset'}});await h.app.refresh(true);
  assert.equal(renders,0);assert.equal(h.get('#report-result').innerHTML,'report result');assert.equal(h.get('#report-date').value,'2026-09-15');
});

test('polling refresh keeps live completion nodes and newly added materials',async()=>{
  const h=harness(),drawer=h.get('#detail-drawer'),oldForm=element(),oldInput=element('unsaved draft'),body=element(),newForm=element();oldInput.id='completion-text';oldForm.children=[oldInput,{material_id:4}];oldForm.querySelector=()=>oldInput;drawer.querySelectorAll=()=>[oldForm];drawer.contains=node=>node===oldInput;
  let replacement=null;newForm.replaceWith=node=>{replacement=node};drawer.querySelector=s=>s==='.drawer-body'?body:s==='#completion-text'?{closest:()=>newForm}:null;
  body.scrollTop=140;h.document.activeElement=oldInput;h.app.S.drawerOrderId=101;h.app.S.drawerStatus='in_progress';
  h.app.override({api:async()=>({order:{id:101,status:'in_progress'}}),renderDrawer(){}});await h.app.refreshDrawer(true);
  assert.equal(replacement,oldForm);assert.equal(replacement.children.length,2);assert.equal(oldInput.value,'unsaved draft');assert.equal(oldInput.focused,true);assert.equal(body.scrollTop,140);
});

test('status changes do not retain forms that are no longer permitted',async()=>{
  const h=harness(),drawer=h.get('#detail-drawer');let formQueries=0;drawer.querySelectorAll=()=>{formQueries++;return []};h.app.S.drawerOrderId=101;h.app.S.drawerStatus='in_progress';
  h.app.override({api:async()=>({order:{id:101,status:'closed'}}),renderDrawer(){}});await h.app.refreshDrawer(true);assert.equal(formQueries,0);assert.equal(h.app.S.drawerStatus,'closed');
});

test('older bootstrap completion cannot overwrite a newer response',async()=>{
  const h=harness(),old=deferred();h.app.S.orderId=null;let n=0;const user=h.app.S.me;
  h.app.override({api:()=>++n===1?old.promise:Promise.resolve({user,marker:'new'}),render(){}});
  const pending=h.app.refresh(true);await h.app.refresh(true);old.resolve({user,marker:'old'});await pending;assert.equal(h.app.S.data.marker,'new');
});

test('late bootstrap cannot restore private state after logout',async()=>{
  const h=harness(),pending=deferred(),user=h.app.S.me;h.app.override({api:()=>pending.promise,render(){}});
  const refresh=h.app.refresh(true);h.app.logoutLocal();pending.resolve({user,marker:'private'});await refresh;assert.equal(h.app.S.me,null);assert.equal(h.app.S.data,null);
});

test('report and audit responses are discarded after switching view',async()=>{
  for(const [view,fn] of [['reports','loadReport'],['audit','loadAudit']]){
    const h=harness(),pending=deferred();h.app.S.view=view;h.get('#report-result');h.get('#view-root').innerHTML='current view';let reports=0;
    h.app.override({api:()=>pending.promise,renderReportResult(){reports++}});const task=h.app[fn]();h.app.S.view='home';pending.resolve({summary:{},items:[]});await task;
    assert.equal(h.app.S.report,null);assert.equal(reports,0);assert.equal(h.get('#view-root').innerHTML,'current view');
  }
});

test('old-session API responses cannot log out a newer session',async()=>{
  const h=harness(),pending=deferred();h.globals.fetch=()=>pending.promise;
  const request=h.app.api('/api/bootstrap');h.app.logoutLocal();h.app.S.me={id:9};pending.resolve({status:401,ok:false,headers:{get:()=> 'application/json'},json:async()=>({error:'expired'})});
  await assert.rejects(request);assert.equal(h.app.S.me.id,9);
});

test('Telegram repeated trigger cancels a pending status request without reopening',async()=>{
  const h=harness(),pending=deferred();let calls=0;
  h.app.override({api:async()=>{calls++;return pending.promise}});
  const opening=h.app.showTelegram();assert.ok(h.document.querySelector('#telegram-popover'));
  await h.app.showTelegram();assert.equal(h.document.querySelector('#telegram-popover'),null);
  pending.resolve({enabled:true,paired:false});await opening;
  assert.equal(calls,1);assert.equal(h.document.querySelector('#telegram-popover'),null);
});

test('Telegram cancel control closes the popover and discards a late status response',async()=>{
  const h=harness(),pending=deferred();h.app.override({api:()=>pending.promise});
  const opening=h.app.showTelegram(),node=h.document.querySelector('#telegram-popover');
  node.querySelector('[data-telegram-cancel]').events.click({currentTarget:node.querySelector('[data-telegram-cancel]')});
  assert.equal(h.document.querySelector('#telegram-popover'),null);
  pending.resolve({enabled:true,paired:false});await opening;
  assert.equal(h.document.querySelector('#telegram-popover'),null);
});

test('Telegram logout invalidates a pending status response in a later session',async()=>{
  const h=harness(),pending=deferred();h.app.override({api:()=>pending.promise});
  const opening=h.app.showTelegram();h.app.logoutLocal();h.app.S.me={id:9,role:'worker'};
  pending.resolve({enabled:true,paired:false});await opening;
  assert.equal(h.document.querySelector('#telegram-popover'),null);
  assert.equal(h.app.S.telegramOutsideHandler,null);
});

test('Telegram logout discards late status and never renders a stale pairing code',async()=>{
  const h=harness(),pair=deferred();
  h.app.override({api:async(path)=>path.endsWith('/status')?{enabled:true,paired:false}:pair.promise});
  await h.app.showTelegram();
  const node=h.document.querySelector('#telegram-popover'),button=node.querySelector('[data-telegram-pair]');
  const action=button.events.click({currentTarget:button});
  h.app.logoutLocal();h.app.S.me={id:22,role:'worker'};
  pair.resolve({command:'/start PRIVATE-ONCE-CODE',expires_at:'2026-10-04T12:00:00Z'});await action;
  assert.equal(h.document.querySelector('#telegram-popover'),null);
  assert.equal(h.localStorageWrites.length,0);
  assert.equal(JSON.stringify(h.logs).includes('PRIVATE-ONCE-CODE'),false);
  assert.equal(h.document.body.children.some(child=>child.innerHTML.includes('PRIVATE-ONCE-CODE')),false);
});

test('manual queue reorder is single-flight and logout discards stale refresh',async()=>{
  const h=harness(),pending=deferred(),calls=[];let refreshes=0;
  h.app.S.session=17;h.app.S.me={id:2,role:'master',csrf:'test'};
  h.app.S.data={work_queues:[{scope:'master:2:worker:4',revision:8,order_ids:[501,502]}],
    orders:[{id:501,priority:'normal'},{id:502,priority:'emergency'}]};
  h.app.override({api:async(path,method,body)=>{calls.push({path,method,body});await pending.promise;return {revision:9}},
    refresh:async()=>{refreshes++}});
  const first=h.app.moveWorkQueue('master:2:worker:4',502,'up');
  const duplicate=h.app.moveWorkQueue('master:2:worker:4',502,'up');
  assert.equal(calls.length,1);
  assert.deepEqual(calls[0].body.order_ids,[502,501]);
  assert.equal(calls[0].body.expected_revision,8);
  assert.equal(h.app.S.data.orders[0].priority,'normal');
  h.app.logoutLocal();pending.resolve();await Promise.all([first,duplicate]);
  assert.equal(refreshes,0);
  assert.equal(calls.length,1);
});

test('rating event shift uses rating_shift without narrowing the roster',async()=>{
  const h=harness(),calls=[];h.app.S.orderId=null;h.app.S.ratingFrom='2026-09-01';h.app.S.ratingTo='2026-09-30';h.app.S.ratingShift='B';
  h.app.override({api:async path=>{calls.push(path);return {user:h.app.S.me}},render(){}});
  await h.app.refresh();const query=new URL('http://local'+calls[0]).searchParams;
  assert.equal(query.get('rating_shift'),'B');assert.equal(query.get('rating_from'),'2026-09-01');assert.equal(query.get('rating_to'),'2026-09-30');assert.equal(query.has('shift_code'),false);
});

function reportInputs(h){
  h.app.S.view='reports';h.get('#report-result');
  for(const [id,value] of Object.entries({'report-from':'2026-09-01','report-to':'2026-09-30','report-brigade':'B','report-shift':'C','report-area':'2','report-equipment':'7','report-worker':'12'}))h.get('#'+id).value=value;
}

test('reports send all server filters, preserve selections and only explicitly request AI',async()=>{
  const h=harness(),calls=[];reportInputs(h);h.get('#load-report');h.app.S.me.role='master';
  h.app.S.data.constants={areas:[{id:2,name:'Area'}],equipment:[{id:7,area_id:2,name:'Asset',code:'EQ7'}],users:[{id:12,role:'worker',display_name:'Worker'}]};
  h.app.override({api:async path=>{calls.push(path);return {summary:{}}},renderReportResult(){}});h.app.bindReportControls();
  await h.get('#load-report').events.click({type:'click'});
  const query=new URL('http://local'+calls[0]).searchParams;
  for(const [key,value] of Object.entries({date_from:'2026-09-01',date_to:'2026-09-30',brigade:'B',shift_code:'C',area_id:'2',equipment_id:'7',worker_id:'12'}))assert.equal(query.get(key),value);
  assert.equal(query.has('include_ai_summary'),false);
  assert.equal(h.app.S.reportArea,'2');assert.equal(h.app.S.reportEquipment,'7');assert.equal(h.app.S.reportWorker,'12');
  const html=h.app.renderReports();for(const id of ['report-area','report-equipment','report-worker'])assert.match(html,new RegExp(`id="${id}"`));
  for(const id of ['2','7','12'])assert.match(html,new RegExp(`value="${id}" selected`));
  await h.app.loadReport({type:'click'});assert.equal(new URL('http://local'+calls[1]).searchParams.has('include_ai_summary'),false);
  await h.app.loadReport(true);assert.equal(new URL('http://local'+calls[2]).searchParams.get('include_ai_summary'),'1');
  for(const id of ['report-area','report-equipment','report-worker'])h.get('#'+id).value='';
  await h.app.loadReport();const cleared=new URL('http://local'+calls[3]).searchParams;
  for(const key of ['area_id','equipment_id','worker_id'])assert.equal(cleared.has(key),false);
});

test('report equipment choices follow area and downtime order choices follow equipment',()=>{
  const h=harness();h.app.S.me.role='master';h.app.S.data.constants.equipment=[{id:3,area_id:1,code:'E3',name:'One'},{id:7,area_id:2,code:'E7',name:'Two'}];
  h.app.S.data.orders=[{id:101,equipment_id:3,code:'ORDER-101',title:'Local <order>'},{id:202,equipment_id:7,code:'ORDER-202',title:'Other'}];
  assert.match(h.app.reportEquipmentOptions('1','3'),/value="3" selected/);assert.doesNotMatch(h.app.reportEquipmentOptions('1','7'),/value="7"/);
  h.get('#report-area').value='2';h.get('#report-equipment').value='3';h.get('#downtime-equipment').value='3';h.get('#downtime-order');h.app.bindReportControls();
  h.get('#report-area').events.change();assert.match(h.get('#report-equipment').innerHTML,/value="7"/);assert.doesNotMatch(h.get('#report-equipment').innerHTML,/value="3"/);
  h.get('#downtime-equipment').events.change();assert.match(h.get('#downtime-order').innerHTML,/ORDER-101/);assert.match(h.get('#downtime-order').innerHTML,/&lt;order&gt;/);assert.doesNotMatch(h.get('#downtime-order').innerHTML,/ORDER-202/);assert.equal(h.get('#downtime-order').disabled,false);
  h.get('#downtime-equipment').value='';h.get('#downtime-equipment').events.change();assert.equal(h.get('#downtime-order').disabled,true);assert.doesNotMatch(h.get('#downtime-order').innerHTML,/ORDER-/);
});

test('reports render refusals and current workload separately with server time semantics',()=>{
  const h=harness();h.get('#report-result');h.app.S.report={summary:{date_from:'2026-09-01',date_to:'2026-09-30',shift_code:'C',issued:3,completed:2,closed:1,refusals:4,current_active_orders:8,current_overdue_orders:6,period_note:'Event UTC <period>',refusals_note:'Actor attribution',workload_note:'No date or shift filter'},worker_totals:[{worker:'Synthetic <worker>',brigade:'A',issued:3,completed:2,closed:1,refusals:4,labor_hours:5,current_active:8,current_in_progress:2,current_queued:3}]};
  h.app.renderReportResult();const html=h.get('#report-result').innerHTML;
  for(const text of ['События за выбранный период','Текущая загрузка · на сейчас','Отказы','Сейчас открыто','Сейчас просрочено','В работе / на паузе','В очереди / доработка','Event UTC &lt;period&gt;','Actor attribution','No date or shift filter'])assert.ok(html.includes(text),text);
  assert.match(html,/<td>Synthetic &lt;worker&gt;<\/td><td>A<\/td><td>3<\/td><td>2<\/td><td>1<\/td><td>4<\/td><td>5<\/td>/);
  assert.match(html,/<td>Synthetic &lt;worker&gt;<\/td><td>8<\/td><td>2<\/td><td>3<\/td>/);
  assert.doesNotMatch(html,/назначенная синтетическая смена/);
});

function downtimeInputs(h){
  h.app.S.me.role='master';h.app.S.view='reports';h.get('#downtime-submit');
  for(const [id,value] of Object.entries({'downtime-equipment':'3','downtime-order':'101','downtime-start':'2026-09-01T08:00','downtime-end':'2026-09-01T09:00','downtime-reason':'Synthetic interval'}))h.get('#'+id).value=value;
}

test('linked downtime keeps numeric order_id and idempotency across failed retries',async()=>{
  const h=harness(),calls=[];downtimeInputs(h);
  h.app.override({api:async(path,method,body)=>{calls.push([path,method,body]);throw new Error('retryable')}});
  await h.app.submitEquipmentDowntime({preventDefault(){}});await h.app.submitEquipmentDowntime({preventDefault(){}});
  assert.equal(calls[0][0],'/api/equipment/downtime');assert.equal(calls[0][1],'POST');assert.equal(calls[0][2].order_id,101);assert.equal(calls[0][2].equipment_id,3);
  assert.equal(calls[0][2].idempotency_key,calls[1][2].idempotency_key);
  h.get('#downtime-order').value='';await h.app.submitEquipmentDowntime({preventDefault(){}});
  assert.equal(calls[2][2].order_id,null);assert.notEqual(calls[1][2].idempotency_key,calls[2][2].idempotency_key);
});

test('downtime submission is single-flight and does not reopen reports after navigation',async()=>{
  const h=harness(),pending=deferred(),calls=[];downtimeInputs(h);
  h.app.override({api:(path,method,body)=>{calls.push([path,method,body]);return pending.promise}});
  const first=h.app.submitEquipmentDowntime({preventDefault(){}});await h.app.submitEquipmentDowntime({preventDefault(){}});
  assert.equal(calls.length,1);assert.equal(h.get('#downtime-submit').disabled,true);
  h.app.S.view='home';h.app.S.viewVersion++;pending.resolve({duplicate:false});await first;
  assert.equal(calls.length,1);assert.equal(h.app.S.downtimeDraft,null);assert.equal(h.app.S.registeringDowntime,false);
});

test('downtime rejects invalid or inverted dates before any write',async()=>{
  const h=harness(),calls=[];downtimeInputs(h);h.app.override({api:async path=>{calls.push(path);return {}}});
  h.get('#downtime-end').value='2026-09-01T07:00';await h.app.submitEquipmentDowntime({preventDefault(){}});
  h.get('#downtime-end').value='invalid';await h.app.submitEquipmentDowntime({preventDefault(){}});assert.equal(calls.length,0);
});

test('a newer filtered report wins over an older in-flight report',async()=>{
  const h=harness(),old=deferred(),next=deferred();reportInputs(h);let requests=0,rendered=0;
  h.app.override({api:()=>++requests===1?old.promise:next.promise,renderReportResult(){rendered++}});
  const first=h.app.loadReport();h.get('#report-worker').value='15';const second=h.app.loadReport();
  next.resolve({summary:{worker_id:15}});await second;old.resolve({summary:{worker_id:12}});await first;
  assert.equal(h.app.S.report.summary.worker_id,15);assert.equal(rendered,1);
});
