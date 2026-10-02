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
  return {value,disabled:false,checked:false,dataset:{},options:[],children:[],events:{},attrs:{},innerHTML:'',textContent:'',id:'',scrollTop:0,isConnected:true,
    classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),toggle:(x,v)=>{if(v===undefined)v=!classes.has(x);v?classes.add(x):classes.delete(x)},contains:x=>classes.has(x)},
    addEventListener(name,fn){this.events[name]=fn},setAttribute(k,v){this.attrs[k]=v},
    append(node){this.children.push(node)},remove(){this.isConnected=false},focus(){this.focused=true},
    contains(node){return this===node||this.children.includes(node)},querySelector(){return null},querySelectorAll(){return []}};
}
function harness() {
  const nodes=new Map(), groups=new Map();
  const get=selector=>{if(!nodes.has(selector))nodes.set(selector,element());return nodes.get(selector)};
  const document={activeElement:null,body:element(),querySelector:s=>nodes.get(s)||null,querySelectorAll:s=>groups.get(s)||[],createElement:()=>element(),addEventListener(){},removeEventListener(){}};
  ['#app','#login-screen','#detail-drawer','#drawer-backdrop','#view-root','#toast-region','#offline-banner'].forEach(get);
  const globals={document,console,navigator:{onLine:true},location:{protocol:'http:',hostname:'example.invalid'},window:{addEventListener(){}},URLSearchParams,setTimeout:()=>0,clearInterval(){},setInterval:()=>1,performance:{now:()=>0},fetch:()=>Promise.reject(new Error('Unexpected real fetch')),FileReader:class{},prompt:()=>null};
  const names=['api','logoutLocal','refresh','refreshDrawer','openOrder','openNewOrder','closeDrawer','saveCompletion','uploadPhotos','createOrder','bindIssueForm','renderDrawer','loadReport','loadAudit','render','runAction','exifPayload','insertJpegExif'];
  const expose=`globalThis.app={S,${names.join(',')},override(overrides){${['api','refresh','renderDrawer','render','syncChrome','compressImage','renderReportResult'].map(n=>`if(overrides.${n})${n}=overrides.${n};`).join('')}}};`;
  const source=fs.readFileSync(sourcePath,'utf8').replace(/\n  bindGlobal\(\);[\s\S]*?\n\}\)\(\);\s*$/,`\n  ${expose}\n})();`);
  vm.runInNewContext(source,globals,{filename:sourcePath});
  const {app}=globals;
  app.S.me={id:1,role:'worker',csrf:'test'};
  app.S.orderId=101;
  app.S.data={constants:{areas:[],equipment:[],users:[],fault_codes:[],materials:[]},free_workers:[]};
  app.override({syncChrome(){}});
  return {app,get,nodes,groups,document,globals};
}
function completionInputs(h) {
  h.get('#completion-text').value='Заменили уплотнение и проверили результат';
  h.get('#fault-code').value='2';h.get('#labor-hours').value='1.5';h.get('#materials-not-used').checked=true;h.get('#save-completion');
}
function issueInputs(h) {
  h.app.S.me.role='master';
  for(const [id,value] of Object.entries({'issue-assignee':'worker:2','issue-title':'Новый наряд','issue-description':'Подробное описание работы','issue-type':'planned','issue-priority':'normal','issue-area':'1','issue-equipment':'3','issue-hours':'8','issue-template':'pump','issue-submit':''}))h.get('#'+id).value=value;
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
