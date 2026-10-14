'use strict';
const $ = s => document.querySelector(s);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let token = new URLSearchParams(location.hash.slice(1)).get('token') || '';
history.replaceState(null, '', location.pathname);
let snapshot = null, cursor = 0, events = [], view = 'tasks', project = 'all', search = '', stateFilter = 'all';
let connected = false, selectedTask = null, taskDetail = null, detailTab = 'results', detailSignature = '', polling = false, toastTimer;
let eventTask = 'all', eventType = 'all', eventLimit = 100, confirmPending = false;
let taskGroup = 'all', lastSyncAt = 0, commandResults = [], commandIndex = 0, clockOffset = 0;
const ago = s => (s=Math.max(0,Math.round(s)))<60?`${s}s`:s<3600?`${Math.floor(s/60)}m ${String(s%60).padStart(2,'0')}s`:`${Math.floor(s/3600)}h ${String(Math.floor(s%3600/60)).padStart(2,'0')}m`;
// Running: how long, and how long since the agent last wrote anything; a long silence may be a hang.
function liveText(task) {
  const now = Date.now()/1000 + clockOffset, quiet = task.last_output ? now - task.last_output : now - task.running_since;
  return `running ${ago(now - task.running_since)} · ${task.last_output ? `last output ${ago(quiet)} ago` : 'no output yet'}${quiet > 300 ? ' · quiet for a while: open Agent output to check' : ''}`;
}
const live = task => task.running_since ? `<p class="queue-hint live-hint" data-live="${escapeHTML(task.id)}">${escapeHTML(liveText(task))}</p>` : '';
const columnLimits = [12,12,12,12];
const names = {tasks:'Control room',plans:'Plans',brainstorm:'Brainstorm',chat:'Agent chat',agents:'Your agents',activity:'Activity log',settings:'Runtime settings'};
const subtitles = {tasks:'Follow each task from queue to verified result.',plans:'A finished brainstorm, followed task by task: what is waiting, running and done.',brainstorm:'Claude and Codex plan together first. Nothing runs until you create the tasks.',chat:'Claude, Codex or a shell in the sandbox: a real terminal. Select to copy, Ctrl+Shift+V to paste.',agents:'Slots, usage, cooldowns and available capabilities.',activity:'Trace decisions and controls for one task or the whole runtime.',settings:'Local transport, reconnect and current boundaries.'};
const terminal = ['COMPLETED','FAILED','CANCELLED','BLOCKED'];
const active = ['RUNNING','VERIFY','REVIEW','WAITING_INPUT','WAITING_APPROVAL','CANCELLING'];
const attentionStates = ['WAITING_INPUT','WAITING_APPROVAL','WAITING_QUOTA','BLOCKED','REVIEW'];
// A task whose questions were merged into a Brainstorm form waits for that form, not for its own row.
const needsYou = task => attentionStates.includes(task.state) && !task.held_by;
const taskGroups = {all:'All tasks',active:'Active attempts',attention:'Needs attention',completed:'Completed tasks'};
const matchesTaskGroup = (task, group=taskGroup) => group === 'all' || (group === 'active' ? active.includes(task.state) : group === 'attention' ? needsYou(task) : task.state === 'COMPLETED');
const shortID = id => (id || 'Not assigned').slice(-6).toUpperCase();
const badge = state => `<span class="badge ${escapeHTML(state.toLowerCase().replaceAll('_','-'))}">${escapeHTML(state.replaceAll('_',' '))}</span>`;
const date = t => new Date(t * 1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
const simulation = () => snapshot?.mode !== 'real';
const currentTask = () => taskDetail?.task?.id === selectedTask ? taskDetail.task : snapshot?.tasks.find(t => t.id === selectedTask);

function updateSystemChrome() {
  $('#system-state').textContent = connected ? 'CONNECTED' : 'OFFLINE';
  $('#system-mode').textContent = snapshot ? (simulation() ? 'SIMULATION MODE' : 'REAL RUNTIME') : 'AWAITING RUNTIME';
  $('#dispatch-state').textContent = !connected ? 'DISPATCH / OFFLINE' : snapshot.paused ? 'DISPATCH / PAUSED' : 'DISPATCH / ENABLED';
  $('.shell').classList.toggle('is-offline', !connected);
  $('.shell').classList.toggle('is-paused', !!snapshot?.paused);
  updateSystemClock();
}

function updateSystemClock() {
  const now = new Date();
  $('#local-clock').textContent = `LOCAL / ${now.toLocaleTimeString('en-GB', {hour12:false})}`;
  $('#local-clock').dateTime = now.toISOString();
  const age = lastSyncAt ? Math.floor((now.getTime()-lastSyncAt)/1000) : null;
  $('#sync-state').textContent = !connected ? (lastSyncAt ? 'SYNC / OFFLINE' : 'SYNC / WAITING') : age <= 5 ? 'SYNC / LIVE' : `SYNC / ${age}s AGO`;
  $('#sync-state').title = lastSyncAt ? `Last confirmed snapshot: ${new Date(lastSyncAt).toLocaleString()}` : 'No snapshot received yet';
}

function navigateView(target) {
  if (!Object.hasOwn(names,target)) return;
  view=target; search=''; stateFilter='all'; taskGroup='all'; render();
}
function showTaskGroup(group) {
  if (!Object.hasOwn(taskGroups,group) || !snapshot) return;
  view='tasks'; taskGroup=group; search=''; stateFilter='all'; render();
  $('#task-search').focus({preventScroll:true});
}
async function openTaskDetail(taskID, openOutput=false) {
  const summary=snapshot?.tasks.find(t=>t.id===taskID);
  if (!summary) return;
  selectedTask=taskID; taskDetail=null;
  detailTab=openOutput||summary.running_since?'log':summary.state==='REVIEW'?'diff':'results'; detailSignature='';
  updateDetail(true);
  if (!$('#detail-dialog').open) $('#detail-dialog').showModal();
  await loadTaskDetail(taskID);
}
function paletteEntries() {
  const commands=[
    {kind:'action',id:'new',title:'Create a new task',meta:'NEW DIRECTIVE / Alt N',icon:'+',disabled:!connected},
    {kind:'action',id:'refresh',title:'Refresh runtime',meta:'SYNC / Reconnect',icon:'↻'},
    {kind:'action',id:'dispatch',title:snapshot?.paused?'Resume dispatch':'Pause dispatch',meta:'CONTROL / Active attempts continue',icon:'Ⅱ',disabled:!connected},
    ...Object.entries(names).map(([id,title],index)=>({kind:'view',id,title:`Go to ${title}`,meta:`WORKSPACE / Alt ${index+1}`,icon:'↗',disabled:!snapshot})),
    {kind:'project',id:'all',title:'All projects',meta:'PROJECT / Clear project filter',icon:'◇',disabled:!snapshot},
  ];
  const projects=(snapshot?.projects||[]).map(p=>({kind:'project',id:p.id,title:p.name,meta:'PROJECT / Switch workspace filter',icon:'◇'}));
  const tasks=(snapshot?.tasks||[]).slice().sort((a,b)=>b.updated_at-a.updated_at).map(t=>({kind:'task',id:t.id,title:t.title,meta:`NAV-${shortID(t.id)} / ${t.state.replaceAll('_',' ')} / ${t.backend}`,keywords:`${t.id} ${t.project_id}`,icon:'▦',disabled:!connected}));
  return [...commands,...projects,...tasks];
}
function paletteMatches(query) {
  const words=query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return paletteEntries().filter(item=>words.every(word=>`${item.title} ${item.meta} ${item.keywords||''}`.toLowerCase().includes(word))).slice(0,20);
}
function selectCommand(index, direction=1, scroll=false) {
  const count=commandResults.length;
  commandIndex=count?(index+count)%count:-1;
  for (let tries=0;tries<count&&commandResults[commandIndex]?.disabled;tries++) commandIndex=(commandIndex+direction+count)%count;
  document.querySelectorAll('[data-command-index]').forEach((el,i)=>el.setAttribute('aria-selected',String(i===commandIndex&&!commandResults[i].disabled)));
  const selected=commandResults[commandIndex];
  if (!selected||selected.disabled) $('#command-search').removeAttribute('aria-activedescendant');
  else {
    $('#command-search').setAttribute('aria-activedescendant',`command-option-${commandIndex}`);
    if (scroll) document.getElementById(`command-option-${commandIndex}`).scrollIntoView({block:'nearest'});
  }
}
function renderCommands(reset=false) {
  const previous=reset?null:commandResults[commandIndex];
  commandResults=paletteMatches($('#command-search').value);
  $('#command-results').innerHTML=commandResults.length?commandResults.map((item,i)=>`<button type="button" id="command-option-${i}" class="command-option" role="option" aria-selected="false" tabindex="-1" data-command-index="${i}" ${item.disabled?'disabled':''}><span class="command-symbol" aria-hidden="true">${item.icon}</span><span class="command-copy"><strong>${escapeHTML(item.title)}</strong><small>${escapeHTML(item.meta)}${item.disabled?' / Unavailable':''}</small></span><span class="command-enter" aria-hidden="true">↵</span></button>`).join(''):'<div class="command-empty">No matches. Try a task title, NAV ID or project name.</div>';
  $('#command-status').textContent=`${commandResults.length} results${commandResults.length===20?' shown; refine your search for more':''}`;
  const index=previous?commandResults.findIndex(item=>item.kind===previous.kind&&item.id===previous.id):0;
  selectCommand(Math.max(0,index));
}
function openCommands() {
  if ($('#command-dialog').open) return;
  if (document.querySelector('dialog[open]')) return;
  $('#command-search').value=''; renderCommands(true);
  $('#command-dialog').showModal(); $('#command-search').focus();
}
async function runCommand(index) {
  const selected=commandResults[index];
  if (!selected||selected.disabled) return;
  // Check current capabilities again; the runtime may change while searching.
  const item=paletteEntries().find(entry=>entry.kind===selected.kind&&entry.id===selected.id);
  if (!item||item.disabled) {renderCommands();return;}
  $('#command-dialog').close();
  if (item.kind==='view') {navigateView(item.id);$('#page-title').focus({preventScroll:true});}
  else if (item.kind==='project') {project=item.id;eventTask='all';navigateView('tasks');$('#page-title').focus({preventScroll:true});}
  else if (item.kind==='task') await openTaskDetail(item.id);
  else if (item.id==='new') openTaskForm();
  else if (item.id==='refresh') await poll();
  else if (item.id==='dispatch') $('#pause').click();
}
function operatorQueue(tasks) {
  const requests=tasks.filter(t=>!t.held_by&&(t.pending||['WAITING_INPUT','WAITING_APPROVAL','REVIEW'].includes(t.state))).sort((a,b)=>a.updated_at-b.updated_at);
  if (!requests.length) return '';
  const action=t=>t.state==='REVIEW'?'Inspect diff':t.state==='WAITING_INPUT'?'Answer request':'Review request';
  return `<section class="operator-queue" aria-label="Operator response queue"><div class="panel-header"><div><span class="eyebrow">OPERATOR REQUIRED</span><h2>${requests.length} decision${requests.length===1?'':'s'} waiting</h2></div><button class="text-button" data-task-group="attention">View attention queue ↗</button></div><div class="operator-requests">${requests.slice(0,4).map(t=>`<button id="operator-task-${escapeHTML(t.id)}" class="operator-request" data-task="${escapeHTML(t.id)}"><span class="request-top"><span>NAV-${escapeHTML(shortID(t.id))}</span>${badge(t.state)}</span><strong>${escapeHTML(t.title)}</strong><span class="request-open">${action(t)} <span aria-hidden="true">↗</span></span></button>`).join('')}</div>${requests.length>4?`<small class="operator-more">+ ${requests.length-4} more in the attention queue</small>`:''}</section>`;
}

function toast(message) {
  $('#toast').textContent = message; $('#toast').hidden = false; $('#announcer').textContent=message;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').hidden = true, 4200);
}
async function api(path, body) {
  const response = await fetch(path, {method:body ? 'POST':'GET',credentials:'same-origin',
    headers:{...(token ? {Authorization:`Bearer ${token}`} : {}),...(body ? {'Content-Type':'application/json'} : {})},
    ...(body ? {body:JSON.stringify(body)} : {}),signal:AbortSignal.timeout(7000)});
  const result = await response.json();
  if (!response.ok) throw Object.assign(new Error(result.error || `Request failed (${response.status})`), {status:response.status, login:result.login});
  return result;
}
async function command(body) {
  if (!connected) { toast('Reconnect before sending controls.'); return null; }
  try { const result = await api('/api/command',body); await poll(); return result; }
  catch (err) { toast(err.message); return null; }
}
function updateAttention(previous, result) {
  const merged = (result.brainstorms||[]).filter(b => (b.questions||[]).some(q => q.gate)).length;  // a merged form has no task with a pending request
  const pending = result.tasks.filter(t => t.pending);
  document.title = pending.length + merged ? `(${pending.length + merged} waiting) Axon — ${names[view]}` : `Axon — ${names[view]}`;
  if (!previous || !document.hidden || !('Notification' in window) || Notification.permission !== 'granted') return;
  const known = new Set(previous.tasks.filter(t=>t.pending).map(t=>t.pending.id));
  const added = pending.filter(t=>!known.has(t.pending.id));
  if (added.length) {
    try { const notification = new Notification('Axon needs your response', {body:`${added.length} task${added.length===1?'':'s'} waiting for input or approval.`,tag:'axon-attention'});
      notification.onclick = () => {window.focus();notification.close();};
    } catch (_) { /* Mobile browsers may require a service worker, which this local UI does not install. */ }
  }
}
async function poll() {
  if (polling) return;
  polling = true;
  try {
    const result = await api(`/api/snapshot?cursor=${cursor}`);
    events = [...events,...result.events].slice(-1000); cursor = result.cursor;
    updateAttention(snapshot,result);
    if (result.now) clockOffset = result.now - Date.now()/1000;
    const changed = !snapshot || !connected || JSON.stringify({...result,events:[],cursor:0,latest_cursor:0,now:0}) !== JSON.stringify({...snapshot,events:[],cursor:0,latest_cursor:0,now:0});
    snapshot = result; connected = true; lastSyncAt=Date.now(); updateSystemChrome();
    if ($('#command-dialog').open) renderCommands();
    $('#connection-alert').hidden = true; $('#local-connection').textContent = 'Connected';
    $('#pause').disabled = false; $('#new-task').disabled = false;
    $('#add-project').hidden = false; $('#add-project').disabled = false;
    $('#runtime-banner').classList.toggle('real-mode',!simulation());
    $('#nav-chat').hidden = simulation(); $('#nav-brainstorm').hidden = simulation(); $('#nav-plans').hidden = simulation();
    $('#runtime-banner').innerHTML = simulation()
      ? '<span class="notice-icon" aria-hidden="true">◌</span><div><strong>Simulation workspace</strong><span>Fake-agent controls only. No repository files are changed.</span></div><span class="notice-badge">SIMULATION / 0.1</span>'
      : '<span class="notice-icon" aria-hidden="true">⌁</span><div><strong>Real runtime</strong><span>Controls and capabilities are provided by the active runner. Verify the task, attempt and diff before approval.</span></div><span class="notice-badge">REAL MODE</span>';
    if (changed || view === 'activity') render();
    if (selectedTask) {
      const summary=result.tasks.find(t=>t.id===selectedTask);
      if (summary && taskDetail?.task?.updated_at===summary.updated_at) updateDetail();
      else await loadTaskDetail(selectedTask);
    }
    updateCountdowns();
  } catch (err) {
    connected = false; updateSystemChrome(); if ($('#command-dialog').open) renderCommands(); $('#local-connection').textContent = 'Disconnected';
    if (err.status===401 && err.login && !$('#login-dialog').open) {$('#login-form .form-error').textContent=''; $('#login-dialog').showModal(); $('#login-password').focus();}
    $('#connection-alert').textContent = err.status===401 ? (err.login ? 'Signed out. Sign in with your Axon password.' : 'Not signed in. Run `axon` on the Axon machine to open it with its launch link.') : 'Connection unavailable. Controls are disabled. If Axon restarted, run `axon` again or reload this page.';
    $('#connection-alert').hidden = false;
    ['#pause','#new-task','#add-project'].forEach(s=>$(s).disabled=true);
    $('#task-detail').querySelectorAll('button[data-action],button[data-continue],button[type="submit"]').forEach(b=>b.disabled=true);
    if (!snapshot) $('#content').innerHTML = `<div class="panel">${empty('Connect your local runtime','Run python -m axon and open its full launch link. Browser-session access survives refresh until the runtime restarts.')}</div>`;
  } finally { polling = false; }
}
function empty(title, description, icon='◈') {
  return `<div class="empty-state"><span class="empty-icon" aria-hidden="true">${icon}</span><strong>${escapeHTML(title)}</strong><p>${escapeHTML(description)}</p></div>`;
}
function filteredTasks() {return snapshot.tasks.filter(t=>project==='all'||t.project_id===project);}
function countdown(until) {
  if (!Number.isFinite(until)) return 'Time unavailable';
  const remaining = Math.max(0,Math.ceil(until-Date.now()/1000));
  return remaining ? `${Math.floor(remaining/60)}:${String(remaining%60).padStart(2,'0')} remaining` : 'Awaiting runtime update';
}
function timer(until) {return `<span data-countdown="${Number(until)}">${escapeHTML(countdown(until))}</span>`;}
function updateCountdowns() {
  document.querySelectorAll('[data-countdown]').forEach(el=>el.textContent = connected ? countdown(Number(el.dataset.countdown)) : 'Disconnected / time unconfirmed');
  document.querySelectorAll('[data-live]').forEach(el=>{const t=currentTask()?.id===el.dataset.live?currentTask():snapshot?.tasks.find(x=>x.id===el.dataset.live); if (t?.running_since) el.textContent=liveText(t);});
}
function queueHint(task) {
  const reasons = task.queue_reasons || [];
  if (task.state === 'WAITING_QUOTA') return `Cooldown / ${timer(task.due)}`;
  return escapeHTML(reasons.map(r=>r.message).join(' · ') || task.activity || 'Waiting for runtime dispatch');
}
function stats(tasks) {
  const running = tasks.filter(t=>active.includes(t.state)).length;
  const waiting = tasks.filter(needsYou).length;
  const completed = tasks.filter(t=>t.state==='COMPLETED').length;
  return `<div class="stats">
    <button type="button" id="stat-all" class="stat" data-task-group="all" aria-describedby="stat-all-value stat-all-detail" aria-label="Show all tasks"><div class="stat-top">Total tasks<span aria-hidden="true">▦</span></div><div id="stat-all-value" class="stat-value">${tasks.length}</div><div id="stat-all-detail" class="stat-footer">Across ${project==='all'?snapshot.projects.length:1} project${project==='all'&&snapshot.projects.length!==1?'s':''}</div></button>
    <button type="button" id="stat-active" class="stat" data-task-group="active" aria-describedby="stat-active-value stat-active-detail" aria-label="Show active attempts"><div class="stat-top">Active attempts<span aria-hidden="true">◌</span></div><div id="stat-active-value" class="stat-value">${running}</div><div id="stat-active-detail" class="stat-footer">${snapshot.paused?'Dispatch paused / active work continues':'See Resources for slot capacity'}</div></button>
    <button type="button" id="stat-attention" class="stat" data-task-group="attention" aria-describedby="stat-attention-value stat-attention-detail" aria-label="Show tasks needing attention"><div class="stat-top">Needs attention<span aria-hidden="true">◷</span></div><div id="stat-attention-value" class="stat-value">${waiting}</div><div id="stat-attention-detail" class="stat-footer">${waiting?'Review, input, cooldown or blocked':'Nothing waiting on you'}</div></button>
    <button type="button" id="stat-completed" class="stat" data-task-group="completed" aria-describedby="stat-completed-value stat-completed-detail" aria-label="Show completed tasks"><div class="stat-top">Completed<span aria-hidden="true">✓</span></div><div id="stat-completed-value" class="stat-value">${completed}</div><div id="stat-completed-detail" class="stat-footer">${simulation()?'Simulated verification only':'Runtime verification evidence'}</div><progress class="completion-progress" value="${completed}" max="${Math.max(1,tasks.length)}" aria-label="Completed tasks">${completed} / ${tasks.length}</progress></button>
  </div>`;
}
function card(task) {
  return `<button id="card-${escapeHTML(task.id)}" class="task-card" data-task="${escapeHTML(task.id)}"><div class="card-top"><span>NAV-${escapeHTML(shortID(task.id))}</span>${badge(task.state)}</div><h3>${escapeHTML(task.title)}</h3><span class="scope-label">⌁ ${escapeHTML(task.scope.join(', '))}</span>${['QUEUED','WAITING_QUOTA'].includes(task.state)?`<p class="queue-hint">${queueHint(task)}</p>`:''}${live(task)}<div class="card-bottom"><span><span class="agent-avatar" aria-hidden="true">${simulation()?'F':'A'}</span>${escapeHTML(task.backend)}</span><span>${date(task.updated_at)}</span></div></button>`;
}
function integrationStrip() {
  if (simulation()) return '';
  return (snapshot.integration||[]).filter(i=>project==='all'||i.project_id===project).map(i=>{
    const checks=i.checks.map(c=>`${escapeHTML(c.name)} ${c.rc?'✗':'✓'}`).join(', ')||'no checks configured';
    const detail=i.busy?`${i.busy==='verify'?'running every check on the merged commit…':`checking the merged commit for task ${escapeHTML(i.busy)}…`}`:`${i.tasks.length} task${i.tasks.length===1?'':'s'} merged at ${escapeHTML((i.commit||'').slice(0,10))} / checks on this exact commit: ${checks}`;
    const why=!i.busy&&!i.can_promote&&i.reason?`<br><small class="muted">${escapeHTML(i.reason)}</small>`:'';
    return `<div class="attention-strip integration-strip"><span aria-hidden="true">⇥</span><span><strong>${escapeHTML(i.project_id)}</strong> integration branch: ${detail}${why}</span><span class="strip-actions">${i.verify_needed&&!i.busy?`<button class="button secondary" data-verify-integration="${escapeHTML(i.project_id)}">Run all checks</button>`:''}${i.review_needed&&!i.busy?`${['claude','codex'].map(a=>`<button class="button secondary" data-review-integration="${escapeHTML(i.project_id)}" data-agent="${a}" ${snapshot.capabilities?.handoff?.[a+'_review']===true?'':`disabled title="${a} is not logged in."`}>Review with ${a==='claude'?'Claude':'Codex'}</button>`).join('')}`:''}<button class="button secondary" data-discard="${escapeHTML(i.project_id)}" ${i.busy?'disabled':''}>Discard</button><button class="button primary" data-promote="${escapeHTML(i.project_id)}" ${i.can_promote&&!i.busy?'':'disabled'}>Fast-forward ${escapeHTML(i.branch||'branch')} →</button></span></div>`;
  }).join('');
}
function board(tasks) {
  const groups = [['Queued',['QUEUED']],['In progress',['RUNNING','VERIFY','REVIEW','CANCELLING']],['Needs attention',['WAITING_INPUT','WAITING_APPROVAL','WAITING_QUOTA','BLOCKED']],['Finished',['COMPLETED','FAILED','CANCELLED']]];
  const visible = tasks.filter(t=>matchesTaskGroup(t)&&(stateFilter==='all'||t.state===stateFilter)&&`${t.title} ${t.spec} ${t.scope.join(' ')}`.toLowerCase().includes(search.toLowerCase()));
  return `<div class="board">${groups.map(([name,states],i)=>{
    const items = visible.filter(t=>states.includes(t.state));
    return `<section class="column" aria-label="${name}"><div class="column-heading"><span class="column-dot" aria-hidden="true"></span>${name}<span class="column-count">${items.length}</span></div>${items.length?items.slice(0,columnLimits[i]).map(card).join(''):'<div class="empty-column">No tasks here yet</div>'}${items.length>columnLimits[i]?`<button class="column-add" data-more-column="${i}">Show 12 more / ${items.length-columnLimits[i]} remaining</button>`:''}${name==='Queued'?'<button class="column-add" data-new-task>+ Add a task</button>':''}</section>`;
  }).join('')}</div>`;
}
function agentRow(name, desc, mark, status, className='', sub='') {
  return `<div class="agent-row"><span class="provider-mark ${className}" aria-hidden="true">${mark}</span><div class="agent-info"><strong>${name}</strong><small>${desc}</small></div><div class="agent-status ${['Ready','Busy','Cooldown'].includes(status)?status.toLowerCase():''}">${status}<span>${sub}</span></div></div>`;
}
function fakeAgentRow() {
  const busy = snapshot.tasks.some(t=>active.includes(t.state));
  const cooldown = snapshot.tasks.filter(t=>t.state==='WAITING_QUOTA'&&t.backend==='fake-agent');
  const until = cooldown.length ? Math.max(...cooldown.map(t=>t.due)) : null;
  return agentRow('Fake agent','In-process simulation / no tools','F',busy?'Busy':cooldown.length?'Cooldown':'Ready','fake',`${busy?'1':'0'} / 1 slots${until?`<br>Task cooldown / ${timer(until)}`:''}`);
}
function providerItems() {
  const marks={fake:'F',codex:'✳',claude:'✽',local:'⌘'};
  if (!simulation()) return (snapshot.providers||[]).map(p=>({name:p.name||p.id,mark:marks[p.id]||'A',desc:p.capability||'Provider reported by runtime',provider:p}));
  return [
    {id:'codex',name:'Codex',mark:'✳',desc:'CLI adapter / feasibility pending'},
    {id:'claude',name:'Claude Code',mark:'✽',desc:'CLI adapter / feasibility pending'},
    {id:'local',name:'Local LLM',mark:'⌘',desc:'Context summaries and log analysis'},
  ].map(item=>({...item,provider:(snapshot.providers||[]).find(p=>p.id===item.id)}));
}
function providerRow(item) {
  const p=item.provider, until=p?.cooldown_until;
  const reported=p?.status||(simulation()?(item.id==='local'?'Not connected':'Not tested'):'Unavailable');
  const status=['Ready','Busy','Cooldown','Unavailable','Not tested','Not connected','Error'].includes(reported)?reported:'Unavailable';
  const slotText=p?.slot_limit!=null?`${p.slots_used??0} / ${p.slot_limit} slots`:p?.reason||(simulation()?'Disabled':'No runtime status');
  const sub=`${escapeHTML(slotText)}${until?`<br>${timer(Number(until))}`:''}`;
  return agentRow(escapeHTML(item.name),escapeHTML(item.desc),item.mark,status,p?.id==='fake'?'fake':status.toLowerCase(),sub)+limitBars(p);
}
function providerCard(item) {
  const p=item.provider;
  return `<section class="panel agent-card">${providerRow(item)}<div class="capability-list"><span class="capability">${escapeHTML(p?.capability||'Status supplied by runtime')}</span></div><p>${escapeHTML(p?.message||'Rate-limit state appears here when the runtime reports a provider cooldown.')}</p></section>`;
}
// What is left of the subscription's 5-hour and weekly windows (the providers report percent used, not tokens).
function limitBars(p) {
  const l = p?.limits; if (!l?.windows?.length) return '';
  const now = Date.now()/1000 + clockOffset;
  const rows = l.windows.map(w => {
    const reset = w.resets_at && w.resets_at < now, left = reset ? 100 : Math.max(0, Math.min(100, 100 - w.used));
    const when = reset ? 'window reset' : w.resets_at ? `resets ${new Date(w.resets_at*1000).toLocaleString([], w.window==='5h'?{hour:'2-digit',minute:'2-digit'}:{weekday:'short',hour:'2-digit',minute:'2-digit'})}` : 'not started';
    return `<div class="limit-row"><span class="limit-name">${escapeHTML(w.window)}</span><meter min="0" max="100" low="20" high="50" optimum="100" value="${left}" aria-label="${escapeHTML(w.window)} left"></meter><span>${Math.round(left)}% left · ${escapeHTML(when)}</span></div>`;
  }).join('');
  const age = now - l.as_of;
  return `<div class="limits">${rows}<small>${age > 600 ? `as of ${ago(age)} ago · updates when ${escapeHTML(p.name)} runs` : `as of ${ago(age)} ago`}</small></div>`;
}
function eventList(limit=8, taskFilter='all', typeFilter='all', sourceEvents=events) {
  const relevant = sourceEvents.filter(e=>(project==='all'||e.project_id===project)&&(taskFilter==='all'||e.task_id===taskFilter)&&(typeFilter==='all'||e.type===typeFilter)).slice(-limit).reverse();
  return relevant.length ? `<div class="timeline">${relevant.map(e=>`<div class="event-row"><span class="event-mark" aria-hidden="true">${e.type==='STATE'?'↗':e.type==='CONTROL'?'Ⅱ':'◇'}</span><div class="event-body"><p>${escapeHTML(e.message)}</p><small>${escapeHTML(e.type)} / ${e.task_id?'NAV-'+escapeHTML(shortID(e.task_id)):'Runtime'} / #${e.seq}</small>${e.task_id?`<button class="text-button" data-task="${escapeHTML(e.task_id)}" data-open-output>Open task output ↗</button>`:''}${typeof e.output==='string'?`<details><summary>Full event output</summary><pre>${escapeHTML(e.output)}</pre></details>`:''}</div><span class="event-time">${date(e.time)}</span></div>`).join('')}</div>` : empty('No matching events','Events retained in the current browser session appear here. Earlier events remain in the database.','≋');
}
async function loadTaskDetail(taskID) {
  if (!connected || !taskID) return;
  try {
    const result = await api(`/api/tasks/${encodeURIComponent(taskID)}`);
    if (selectedTask !== taskID) return;
    taskDetail = result; detailSignature = ''; updateDetail();
  } catch (err) {
    if (selectedTask === taskID) toast(`Task evidence unavailable: ${err.message}`);
  }
}
function eventToolbar(tasks) {
  return `<div class="event-toolbar"><label>Task<select id="event-task"><option value="all">All tasks and runtime</option>${tasks.map(t=>`<option value="${escapeHTML(t.id)}" ${eventTask===t.id?'selected':''}>${escapeHTML(t.title)}</option>`).join('')}</select></label><label>Event type<select id="event-type"><option value="all">All event types</option>${[...new Set(events.map(e=>e.type))].sort().map(type=>`<option ${eventType===type?'selected':''}>${escapeHTML(type)}</option>`).join('')}</select></label></div>`;
}
// The readable agent log: what the agent said stands out, tool calls are one line each, their output is dimmed.
const logLine = line => `<span class="${/^(→|\?)/.test(line)?'log-tool':/^(■|✗)/.test(line)?'log-status':/^ {2}/.test(line)?'log-result':'log-text'}">${escapeHTML(line)}</span>`;
function artifactBlock(artifact, task, expanded=false) {
  const conversation = artifact.kind==='agent_log' && !String(artifact.id).startsWith('agent_log_raw');
  const body = conversation ? `<pre class="conversation">${String(artifact.content??'').split('\n').map(logLine).join('\n')}</pre>` : `<pre>${escapeHTML(artifact.content)}</pre>`;
  return `<details ${expanded&&!String(artifact.id).startsWith('agent_log_raw')?'open':''}><summary>${escapeHTML(artifact.name)} / ${artifact.simulated?'SIMULATED':'RUNTIME EVIDENCE'}</summary><small>Attempt ${escapeHTML(artifact.attempt_id)} / SHA-256 ${escapeHTML(artifact.hash||'not supplied')}</small>${body}<button class="text-button" data-copy-artifact="${escapeHTML(artifact.id)}" data-copy-task="${escapeHTML(task.id)}">Copy full result</button></details>`;
}
function formatBytes(bytes) {
  if (!Number.isFinite(Number(bytes)) || Number(bytes)<0) return 'Not measured';
  const units=['B','KiB','MiB','GiB']; let value=Number(bytes), index=0;
  while(value>=1024&&index<units.length-1){value/=1024;index++;}
  return `${value.toFixed(index?1:0)} ${units[index]}`;
}
function usagePanel() {
  const rows=snapshot.usage||[]; if (simulation()) return '';
  const k=n=>n>=10000?`${(n/1000).toFixed(1)}k`:String(n);
  return `<section class="panel"><div class="panel-header"><h2>Usage, last 24 hours</h2><span class="muted">What each CLI exposed; blank means it exposed nothing</span></div>${rows.length?`<table class="usage-table"><thead><tr><th>Agent</th><th>Kind</th><th>Attempts</th><th>Time</th><th>Axon prompt</th><th>Input tokens</th><th>Output</th><th>Cost</th><th>Settings</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${escapeHTML(r.agent)}</td><td>${escapeHTML(r.kind)}</td><td>${r.attempts} (${escapeHTML(Object.entries(r.outcomes).map(([o,n])=>`${o}:${n}`).join(' '))})</td><td>${Math.round(r.seconds)} s</td><td>${(r.prompt_bytes/1024).toFixed(1)} KB</td><td>${r.with_usage?`${k(r.input)} (${k(r.cached)} cached)`:'-'}</td><td>${r.with_usage?k(r.output):'-'}</td><td>${r.with_usage&&r.cost_usd?`$${r.cost_usd.toFixed(3)}`:'-'}</td><td>${escapeHTML(r.settings.join(', '))}</td></tr>`).join('')}</tbody></table>`:'<p class="muted">No finished attempts in the last 24 hours.</p>'}</section>`;
}
function resourcePanel() {
  const slots = snapshot.resources?.slots || [];
  const attempts = filteredTasks().filter(t=>active.includes(t.state));
  const memoryFor=t=>{const attempt=t.attempts.find(a=>a.id===t.attempt_id);return attempt?.memory_bytes??snapshot.resources?.attempt_memory_bytes?.[t.attempt_id]??null;};
  const sampled=attempts.filter(t=>memoryFor(t)!==null).length;
  return `<section class="panel"><div class="panel-header"><h2>Dispatch capacity</h2><span class="badge">${simulation()?'SIMULATION':'RUNTIME'}</span></div><dl class="settings-list">${slots.map(s=>`<div><dt>${escapeHTML(s.backend)} slots</dt><dd>${escapeHTML(s.used)} / ${escapeHTML(s.limit)}</dd></div>`).join('')||'<div><dt>Slots</dt><dd>Not reported by runtime</dd></div>'}<div><dt>Dispatch</dt><dd>${snapshot.paused?'Paused':'Enabled'}</dd></div><div><dt>Attempt RAM</dt><dd>${sampled} of ${attempts.length} active attempts measured</dd></div></dl><div class="detail-section"><h3>Active attempts</h3>${attempts.length?`<div class="table-scroll"><table class="resource-table"><thead><tr><th scope="col">Task</th><th scope="col">Attempt</th><th scope="col">Agent</th><th scope="col">Memory</th></tr></thead><tbody>${attempts.map(t=>`<tr><td><button class="text-button" data-task="${escapeHTML(t.id)}">${escapeHTML(t.title)}</button></td><td>${escapeHTML(t.attempt_id)}</td><td>${escapeHTML(t.backend)}</td><td>${escapeHTML(formatBytes(memoryFor(t)))}</td></tr>`).join('')}</tbody></table></div>`:empty('No active attempts','Dispatch capacity is available when the runtime is not paused.')}</div><p class="muted">${simulation()?'The fake agent has no separate worker process or per-attempt RAM sample.':'RAM values are shown only when the runtime supplies measured memory_bytes.'}</p></section>`;
}
function settingsPanel() {
  return settingsBase()+agentOptionsPanel();
}
function settingsBase() {
  const settings=snapshot.settings;
  if (!settings?.editable || !Array.isArray(settings.items)) return `<section class="panel"><h2>Runtime settings</h2><p class="muted">${simulation()?'The simulation uses one fixed slot.':'Settings are read-only until the runtime exposes editable settings.'}</p><dl class="settings-list">${[['Mode',simulation()?'Simulation only':'Real'],['Transport','Authenticated loopback'],['Remote listener','Disabled'],['Dispatch',snapshot.paused?'Paused':'Enabled']].map(([k,v])=>`<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')}</dl></section>`;
  return `<section class="panel"><h2>Runtime settings</h2><form id="settings-form">${settings.items.map(x=>`<label>${escapeHTML(x.label)}<input name="${escapeHTML(x.key)}" type="${x.type==='number'?'number':'text'}" value="${escapeHTML(x.value)}" ${Number.isFinite(x.min)?`min="${x.min}"`:''} ${Number.isFinite(x.max)?`max="${x.max}"`:''} ${x.required?'required':''}></label>`).join('')}<p class="form-error" role="alert"></p><button class="button primary" type="submit">Save runtime settings</button></form></section>`;
}
function agentOptionsPanel() {
  const ao=snapshot.agent_options; if (simulation()||!ao) return '';
  const names={claude:'Claude Code',codex:'Codex'};
  return `<section class="panel" id="agent-options-panel"><h2>Model and effort</h2><p class="muted">Applies to attempts that start from now on. Leave blank for the CLI's own default. A task can override these when it is created.</p><form id="agent-options-form">${Object.entries(ao).map(([agent,o])=>`<fieldset><legend>${escapeHTML(names[agent]||agent)}</legend><div class="form-row"><label>Model<input name="${escapeHTML(agent)}_model" list="models-${escapeHTML(agent)}" value="${escapeHTML(o.model)}" maxlength="80" placeholder="default" autocomplete="off"><datalist id="models-${escapeHTML(agent)}">${o.models.map(m=>`<option value="${escapeHTML(m)}">`).join('')}</datalist></label><label>Effort<select name="${escapeHTML(agent)}_effort"><option value="">Default</option>${o.efforts.map(e=>`<option ${e===o.effort?'selected':''}>${escapeHTML(e)}</option>`).join('')}</select></label></div></fieldset>`).join('')}<p class="form-error" role="alert"></p><button class="button primary" type="submit">Save model and effort</button></form></section>`;
}
function rememberFocus() {
  const element = document.activeElement;
  return {id:element?.id,start:element?.selectionStart,end:element?.selectionEnd};
}
function restoreFocus(saved) {
  if (!saved.id) return;
  const element = document.getElementById(saved.id);
  if (!element) return;
  element.focus({preventScroll:true});
  if (typeof element.setSelectionRange==='function'&&typeof saved.start==='number') element.setSelectionRange(saved.start,saved.end);
}
function render() {
  if (!snapshot) return;
  const focus = rememberFocus();
  $('#command-masthead').hidden = view !== 'tasks';
  $('#page-title').textContent = names[view]; $('#page-subtitle').textContent = subtitles[view]; $('#view-label').textContent = names[view];
  document.querySelectorAll('.sidebar .nav-item').forEach(b=>{b.classList.toggle('active',b.dataset.view===view);if(b.dataset.view===view)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
  $('#pause').textContent = snapshot.paused?'▷ Resume dispatch':'Ⅱ Pause dispatch';
  $('#nav-task-count').textContent = snapshot.tasks.length;
  $('#add-project').hidden = false;
  $('#project-list').innerHTML = `<button id="project-all" class="project-item ${project==='all'?'active':''}" data-project="all"><span class="project-dot" aria-hidden="true"></span><span>All projects</span></button>`+snapshot.projects.map(p=>`<button id="project-${escapeHTML(p.id)}" class="project-item ${project===p.id?'active':''}" data-project="${escapeHTML(p.id)}"><span class="project-dot" aria-hidden="true"></span><span>${escapeHTML(p.name)}</span></button>`).join('');
  const tasks = filteredTasks(); let html = '';
  if (view==='tasks') {
    html = stats(tasks);
    html += integrationStrip();
    html += operatorQueue(tasks);
    html += `<div class="section-title"><h2>Task board <small>${project==='all'?'All projects':escapeHTML(snapshot.projects.find(p=>p.id===project)?.name)}</small></h2><button class="text-button" data-new-task>+ Create task</button></div>`;
    html += `<div class="board-toolbar"><input id="task-search" placeholder="Search tasks…" aria-label="Search tasks" value="${escapeHTML(search)}"><select id="group-filter" aria-label="Filter task group">${Object.entries(taskGroups).map(([id,label])=>`<option value="${id}" ${taskGroup===id?'selected':''}>${label}</option>`).join('')}</select><select id="state-filter" aria-label="Filter by state"><option value="all">All states</option>${[...new Set(snapshot.tasks.map(t=>t.state))].sort().map(s=>`<option ${s===stateFilter?'selected':''}>${escapeHTML(s)}</option>`).join('')}</select></div>`;
    html += board(tasks);
  } else if (view==='agents') {
    const fakeCard=simulation()?`<section class="panel agent-card">${fakeAgentRow()}<div class="capability-list"><span class="capability">Lifecycle simulation</span><span class="capability">Task cooldown</span><span class="capability">Source artifact references</span></div><p>Controls run in-process. A task cooldown releases the slot; it does not imply the whole fake provider is blocked.</p></section>`:'';
    const cards=providerItems().map(providerCard).join('');
    html = `<div class="agent-grid">${fakeCard}${cards||`<section class="panel">${empty('No providers reported','Provider status appears when the runtime supplies it.')}</section>`}</div>`+resourcePanel()+usagePanel();
  } else if (view==='activity') html = `<section class="panel event-log"><div class="panel-header"><h2>Runtime events</h2><span class="muted">Cursor ${cursor} / latest 1,000 retained in this tab</span></div>${eventToolbar(tasks)}${eventList(eventLimit,eventTask,eventType)}${eventLimit<1000?'<button class="text-button" id="more-events">Show more events</button>':''}</section>`;
  else if (view==='plans') html = simulation()?`<section class="panel">${empty('Not in the simulation','Plans come from Brainstorm, which needs the real runtime and your agents.')}</section>`:plansView();
  else if (view==='chat') {if ($('#chat-root')) return; html = chatPanel(); chatDisconnect(); chatSession='';}
  else if (view==='brainstorm') {if ($('#bs-root')) {bsRefresh(); updateAttention(null,snapshot); return;} html = simulation()?`<section class="panel">${empty('Not in the simulation','Brainstorm needs the real runtime and your agents.')}</section>`:brainstormPanel();}
  else html = settingsPanel();
  if (view!=='chat') chatDisconnect();
  $('#content').innerHTML = html; restoreFocus(focus); updateAttention(null,snapshot); updateCountdowns();
  if (view==='chat') chatTick();
  if (view==='brainstorm') bsRefresh();
}
function populateSources(selected='') {
  const projectID = $('#task-project').value;
  $('#task-source').innerHTML = '<option value="">New task / no source</option>'+snapshot.tasks.filter(t=>t.project_id===projectID&&t.state==='COMPLETED').map(t=>`<option value="${escapeHTML(t.id)}" data-attempt="${escapeHTML(t.attempt_id)}" ${t.id===selected?'selected':''}>${escapeHTML(t.title)} / ${escapeHTML(shortID(t.attempt_id))}</option>`).join('');
}
function syncFlowRow() {
  const row=$('#task-flow-row'), help=$('#task-flow-help'), pid=$('#task-project').value;
  const proj=snapshot.projects.find(x=>x.id===pid), real=!simulation();
  row.hidden=help.hidden=!real;
  if (!real) return;
  $('#task-after').innerHTML='<option value="">No dependency</option>'+snapshot.tasks.filter(t=>t.project_id===pid&&t.kind==='task'&&!['FAILED','CANCELLED'].includes(t.state)).map(t=>`<option value="${escapeHTML(t.id)}">${escapeHTML(t.title)} (${escapeHTML(t.state)})</option>`).join('');
  const names=proj?.checks||[];
  $('#task-checks-list').innerHTML=names.length?names.map(n=>`<label class="inline-check"><input type="checkbox" name="checks" value="${escapeHTML(n)}"> ${escapeHTML(n)}</label>`).join(' '):'<span class="muted">This project has no checks.</span>';
}
function syncModelRow() {
  const row=$('#task-model-row'), agent=$('#task-agent').value, o=(snapshot.agent_options||{})[agent];
  row.hidden = simulation()||!o;
  if (!o) return;
  $('#task-model-list').innerHTML=o.models.map(m=>`<option value="${escapeHTML(m)}">`).join('');
  $('#task-model').placeholder=o.model?`default: ${o.model}`:'default';
  $('#task-effort').innerHTML=`<option value="">${o.effort?`Default (${escapeHTML(o.effort)})`:'Default'}</option>`+o.efforts.map(e=>`<option>${escapeHTML(e)}</option>`).join('');
}
function openTaskForm(source=null) {
  $('#task-form').reset(); $('#task-form .form-error').textContent = '';
  const agentSelect = $('#task-agent'), isReal = !simulation();
  agentSelect.disabled = !isReal; agentSelect.name = isReal ? 'agent' : '';
  if (isReal) agentSelect.innerHTML = (snapshot.providers||[]).map(p=>`<option value="${escapeHTML(p.id)}" ${p.ok?'':'disabled'}>${escapeHTML(p.name)}${p.ok?'':` (${escapeHTML((p.reason||'unavailable').toLowerCase())})`}</option>`).join('');
  $('#task-scenario').closest('label').hidden = isReal;
  agentSelect.onchange = syncModelRow; syncModelRow();
  $('#create-description').textContent = isReal ? 'The agent works in a sandboxed clone of the project; your checkout is never touched.' : 'This task runs against a simulated agent. It cannot access your repository.';
  $('#source-description').textContent = isReal ? 'The new task starts from the result commit of that task (its refs/axon/attempts/* ref).' : 'Source artifacts are copied as a simulation context reference; no Git branch is created.';
  $('#task-project').innerHTML = snapshot.projects.map(p=>`<option value="${escapeHTML(p.id)}" ${(source?.project_id||project)===p.id?'selected':''}>${escapeHTML(p.name)}</option>`).join('');
  populateSources(source?.id||'');
  syncFlowRow();
  if (source) {$('#task-title').value = `Continue: ${source.title}`.slice(0,120);$('#task-spec').value = `Continue the work from “${source.title}”.\n\nDescribe the next outcome and acceptance criteria.`;$('#task-scope').value = source.scope.join(', ');}
  $('#task-dialog').showModal();
}
function renderDiff(task) {
  const patches = task.artifacts.filter(a=>a.kind==='diff');
  if (!patches.length) return empty('No Git diff is available',simulation()?'This simulation does not read or edit a repository. A real runner must supply a commit-bound patch and per-file policy classification.':'The runtime has not supplied a patch. A file-stat summary cannot substitute for reviewing code.','⌁');
  return patches.map(a=>`<section><small>Attempt ${escapeHTML(a.attempt_id)} / ${a.simulated?'SIMULATED PATCH':'RUNTIME PATCH'} / SHA-256 ${escapeHTML(a.hash||'not supplied')}</small>${(a.files||[]).map(f=>`<div class="file-row"><code>${escapeHTML(f.path)}</code><span class="badge">${f.out_of_scope===true?'OUT OF SCOPE':f.out_of_scope===false?'IN SCOPE':'SCOPE NOT CLASSIFIED'}</span><span class="badge">${f.protected===true?'PROTECTED':f.protected===false?'NOT PROTECTED':'PROTECTION NOT CLASSIFIED'}</span></div>`).join('')}<pre aria-label="Full code diff">${String(a.content||'').split('\n').map(line=>`<span class="diff-line ${line.startsWith('diff ')||line.startsWith('@@')?'diff-header':line.startsWith('+')?'diff-add':line.startsWith('-')?'diff-remove':''}">${escapeHTML(line)}</span>`).join('')}</pre><button class="text-button" data-copy-artifact="${escapeHTML(a.id)}" data-copy-task="${escapeHTML(task.id)}">Copy full patch</button></section>`).join('');
}
function detailPanel(task) {
  if (detailTab==='diff') return renderDiff(task);
  if (detailTab==='log') {
    const logs = task.artifacts.filter(a=>a.kind==='agent_log');
    return (logs.length ? logs.map(a=>artifactBlock(a,task,true)).join('') : empty('Agent output is unavailable','There is no real agent.log in this version. Runtime event output is shown below.','≋'))+eventList(1000,task.id,'all',taskDetail?.events||events);
  }
  if (detailTab==='prompt') {
    const prompts = task.artifacts.filter(a=>a.kind==='prompt');
    return prompts.length ? prompts.map(a=>artifactBlock(a,task,true)).join('') : `${empty('No provider prompt was sent','These are the task instructions saved in Axon. They are not a prompt delivered to a model.')}<pre>${escapeHTML(task.spec)}</pre>${task.instructions.map(i=>`<pre>Instruction v${i.version}\n${escapeHTML(i.text)}</pre>`).join('')}`;
  }
  if (detailTab==='attempts') return task.attempts.map(a=>`<div class="detail-section"><small>${escapeHTML(a.id)} / ${date(a.started_at)} / ${escapeHTML(a.backend)}${a.model||a.effort?` / ${escapeHTML(a.model||'default')} · ${escapeHTML(a.effort||'default')}`:''}${a.usage?` / ${a.usage.input} in (${a.usage.cached} cached) · ${a.usage.output} out${a.usage.cost_usd?` · $${a.usage.cost_usd.toFixed(3)}`:''}`:''}</small>${badge(a.state||'RUNNING')}</div>`).join('') || empty('Waiting for dispatch','No attempt has started yet.');
  return task.artifacts.filter(a=>!['diff','agent_log','prompt'].includes(a.kind)).map(a=>artifactBlock(a,task,true)).join('') || empty('No results yet','Result and verification evidence will appear here after a simulated step.','◇');
}
function updateDetail(force=false) {
  const task = currentTask(); if (!task) return;
  const signature = JSON.stringify([task,detailTab,connected,events.length]);
  if (!force&&signature===detailSignature) return;
  const focus = rememberFocus();
  const saved = {}; $('#task-detail').querySelectorAll('textarea').forEach(el=>saved[el.name]=el.value);
  const disclosureState = [...$('#task-detail').querySelectorAll('details')].map(el=>el.open);
  const pres = [...$('#task-detail').querySelectorAll('pre')].map(el=>el.scrollHeight-el.scrollTop-el.clientHeight<40 ? -1 : el.scrollTop);
  const dialogTop = $('#detail-dialog').scrollTop;
  detailSignature = signature;
  const controls = [];
  const gracefulStop=simulation()||snapshot.capabilities?.controls?.graceful_stop===true;
  if (!terminal.includes(task.state)) {
    if (gracefulStop) controls.push('<button class="button secondary" data-action="stop">■ Stop gracefully</button>');
    else if (active.includes(task.state)) controls.push('<button class="button danger" data-action="kill">Terminate attempt</button>');
    else controls.push('<button class="button secondary" data-action="stop">Cancel queued task</button>');
  }
  if (active.includes(task.state)&&gracefulStop) controls.push(`<button class="button danger" data-action="kill">${simulation()?'Kill simulation':'Force kill process tree'}</button>`);
  if (['FAILED','CANCELLED','BLOCKED'].includes(task.state)) controls.push('<button class="button primary" data-action="retry">↻ Retry as new attempt</button>');
  if (task.state==='COMPLETED') {
    controls.push(`<button class="button primary" data-continue="${escapeHTML(task.id)}">Continue from this task →</button>`);
    const handoff=snapshot.capabilities?.handoff||{};
    controls.push(`<button class="button secondary" data-action="review_with_claude" ${handoff.claude_review===true?'':'disabled title="Claude review is unavailable until the runtime reports a logged-in adapter."'}>Review with Claude</button>`);
    controls.push(`<button class="button secondary" data-action="continue_with_codex" ${handoff.codex_continue===true?'':'disabled title="Codex continuation is unavailable until the runtime reports a logged-in adapter."'}>Continue with Codex</button>`);
    controls.push(`<button class="button secondary" data-action="review_with_codex" ${handoff.codex_review===true?'':'disabled title="Codex is not logged in."'}>Review with Codex</button>`);
    controls.push(`<button class="button secondary" data-action="continue_with_claude" ${handoff.claude_continue===true?'':'disabled title="Claude is not logged in."'}>Continue with Claude</button>`);
  }
  if (!simulation()&&task.state==='COMPLETED'&&task.head&&task.kind==='task') controls.push('<button class="button primary" data-action="apply" title="Write these changes into your project folder as uncommitted edits. Nothing is written if your own edits touch the same lines.">Apply to my folder</button>');
  if (!simulation()&&task.state==='COMPLETED'&&task.head&&task.kind==='task') controls.push('<button class="button primary" data-action="integrate" title="Merge this result into the Axon integration branch and run the checks on the merged commit. Your branch is not touched.">Add to integration branch</button>');
  if (!simulation()&&task.state==='COMPLETED'&&typeof task.result_ref==='string'&&/^refs\/axon\/attempts\/[a-zA-Z0-9][a-zA-Z0-9._/-]*$/.test(task.result_ref)&&!task.result_ref.includes('..')) controls.push('<button class="button secondary" data-copy-merge>Copy merge command</button>');
  const latestReview = (task.reviews||[])[0];
  if (!simulation()&&task.state==='COMPLETED'&&task.kind==='task'&&latestReview&&latestReview.verdict==='changes'&&!latestReview.stale) controls.push('<button class="button primary" data-action="revise" title="Queue a bounded follow-up round that starts from this result and carries the reviewer findings.">Revise from review</button>');
  let request = '';
  if (task.pending) request = `<section class="request-box"><h3>${task.state==='WAITING_APPROVAL'?'Approval required':'Your input is needed'}</h3><p>${escapeHTML(task.pending.message)}</p><small>Expires at ${date(task.pending.expires)} / bound to the displayed attempt</small>${(task.pending.questions||[]).length?multiAsk(task.pending.questions,'data-detail-ask'):''}${(task.pending.questions||[]).length&&task.state==='WAITING_INPUT'?'':task.state==='WAITING_APPROVAL'?`<div class="detail-actions"><button class="button primary" data-action="approve">${simulation()?'Approve simulation':'Approve request'}</button><button class="button danger" data-action="reject">Reject</button></div>`:`${(task.pending.options||[]).length?`<div class="answer-options" role="group" aria-label="Choose an answer">${task.pending.options.map((o,i)=>`<button type="button" class="button secondary" data-answer-option="${i}">${escapeHTML(o)}</button>`).join('')}</div><p class="field-help">Or write your own answer:</p>`:''}<form id="answer-form"><label>Your answer<textarea id="task-answer" name="answer" required maxlength="2000" rows="2"></textarea></label><button class="button primary" type="submit">Send answer →</button></form>`}</section>`;
  else if (task.held_by) request = `<section class="request-box"><h3>Answered in Brainstorm #${escapeHTML(task.held_by)}</h3><p>This agent's questions were merged with the other agent's, so you answer them once, in the Brainstorm page.</p></section>`;
  else if (task.state==='REVIEW') request = `<section class="request-box"><h3>Approve reviewed attempt</h3><p>The runner has not supplied a separate approval question. Review the diff and verification evidence above before approving.</p><div class="detail-actions"><button class="button primary" data-action="approve">Approve attempt</button><button class="button danger" data-action="reject">Reject attempt</button></div></section>`;
  else if (task.state==='WAITING_INPUT') request = `<section class="request-box"><h3>Waiting for your input</h3><p>The runtime has not supplied the input prompt yet. Refresh the task details or inspect its event output.</p><button class="text-button" data-open-output data-task="${escapeHTML(task.id)}">Open task output ↗</button></section>`;
  const reviewItems = (task.reviews||[]).map(r=>`<li><strong>${r.verdict==='approve'?'Approved':'Changes requested'}</strong> by ${escapeHTML(r.reviewer)}${r.reviewer===r.implementer?' (same agent as the implementer)':''}${r.stale?' / reviewed an older result, not this commit':''}<br><span class="muted">${String(r.summary||'').split('\n').map(escapeHTML).join('<br>')}</span></li>`).join('');
  const reviewBlock = (reviewItems||task.round) ? `<section class="detail-section"><h3>Reviews</h3>${task.round?`<p class="muted">Revision round ${task.round}</p>`:''}<ul class="queue-reasons">${reviewItems}</ul></section>` : '';
  const reasons = task.queue_reasons || [];
  const tabLabels=[['results','Results'],['diff','Code diff'],['log','Agent output'],['prompt','Prompt / instructions'],['attempts','Attempts']];
  const activeLabel=tabLabels.find(([id])=>id===detailTab)?.[1]||'Results';
  $('#task-detail').innerHTML = `<div class="dialog-heading"><div><span class="eyebrow">NAV-${escapeHTML(shortID(task.id))} / ${simulation()?'SIMULATION':'RUNTIME'}</span><h2 id="detail-title">${escapeHTML(task.title)}</h2></div><button class="icon-button" data-close="detail-dialog" aria-label="Close task details">×</button></div><div class="detail-meta">${badge(task.state)}<span class="muted">${escapeHTML(task.backend)}</span></div>${task.state==='REVIEW'?'<div class="review-callout"><strong>Review required</strong><span>Inspect the complete diff, file policy labels and verification evidence before approving this attempt.</span></div>':''}<p class="detail-description">${escapeHTML(task.spec)}</p><div class="detail-fields"><div><span>Scope</span>${escapeHTML(task.scope.join(', '))}</div><div><span>Current attempt</span>${escapeHTML(task.attempt_id||'Not dispatched')}</div><div><span>Attempts</span>${task.attempts.length}</div>${task.checks?`<div><span>Verified by</span>${escapeHTML(task.checks.join(', '))}</div>`:''}${task.after?`<div><span>Starts after</span>task ${escapeHTML(task.after)}</div>`:''}${(snapshot.agent_options||{})[task.backend]?`<div><span>Model / effort</span>${escapeHTML(task.model||'default')} / ${escapeHTML(task.effort||'default')}</div>`:''}${simulation()?`<div><span>Scenario</span>${escapeHTML(task.scenario)}</div>`:`<div><span>Result commit</span>${escapeHTML((task.head||'none').slice(0,12))}</div>`}</div><p class="muted">${escapeHTML(task.activity)}</p>${live(task)}${reasons.length?`<ul class="queue-reasons">${reasons.map(r=>`<li>${escapeHTML(r.message)}${r.until?` / ${timer(r.until)}`:''}${r.task_id?`<button class="text-button" data-task="${escapeHTML(r.task_id)}">Open blocking task ↗</button>`:''}</li>`).join('')}</ul>`:''}${task.source?`<div class="detail-section"><h3>Source task</h3><button class="text-button" data-task="${escapeHTML(task.source.task_id)}">${escapeHTML(task.source.title)} ↗</button><small>Attempt ${escapeHTML(task.source.attempt_id)} / ${task.source.artifacts.length} saved artifact references</small></div>`:''}${request}${reviewBlock}<div class="detail-actions">${controls.join('')}</div><div class="detail-tabs" role="tablist" aria-label="Task evidence">${tabLabels.map(([id,label])=>`<button type="button" id="detail-tab-${id}" role="tab" class="detail-tab" data-detail-tab="${id}" aria-selected="${detailTab===id}" aria-controls="detail-evidence" tabindex="${detailTab===id?'0':'-1'}">${label}</button>`).join('')}</div><section id="detail-evidence" role="tabpanel" tabindex="0" aria-labelledby="detail-tab-${detailTab}" aria-label="${escapeHTML(activeLabel)}" aria-busy="${!taskDetail}">${!taskDetail?empty('Loading task evidence','Only the selected task’s full diff, log, prompt and artifacts are being loaded.'):detailPanel(task)}</section>${!terminal.includes(task.state)&&task.state!=='CANCELLING'?'<section class="detail-section"><h3>Add an instruction</h3><form id="instruction-form"><label>Versioned guidance for the next step<textarea id="task-instruction" name="instruction" rows="2" required maxlength="2000"></textarea></label><button class="button secondary" type="submit">Save instruction</button></form></section>':''}`;
  $('#task-detail').querySelectorAll('textarea').forEach(el=>{if(saved[el.name])el.value=saved[el.name];});
  if (!force) $('#task-detail').querySelectorAll('details').forEach((el,i)=>{if(i<disclosureState.length)el.open=disclosureState[i];});
  if (!force) {$('#detail-dialog').scrollTop = dialogTop; $('#task-detail').querySelectorAll('pre').forEach((el,i)=>{if (i<pres.length) el.scrollTop = pres[i]<0 ? el.scrollHeight : pres[i];});}
  else if (detailTab==='log') $('#task-detail').querySelectorAll('pre.conversation').forEach(el=>el.scrollTop=el.scrollHeight);
  if (!connected) $('#task-detail').querySelectorAll('button[data-action],button[data-continue],button[type="submit"]').forEach(b=>b.disabled=true);
  restoreFocus(focus); updateCountdowns();
}
function taskCommand(action, extra={}) {
  const task = currentTask(); if (!task) return Promise.resolve(null);
  return command({action,task_id:task.id,attempt_id:task.attempt_id,...extra});
}
function confirmControl(action, task, info) {
  if (confirmPending) return Promise.resolve(false);
  confirmPending = true;
  const dialog = $('#confirm-dialog'); dialog.returnValue = '';
  if (action==='promote'||action==='discard') {
    const discard = action==='discard';
    $('#confirm-title').textContent = discard ? 'Discard the integration branch?' : 'Fast-forward your branch?';
    $('#confirm-description').textContent = discard ? 'Drops the Axon integration branch. Completed tasks stay completed and can be integrated again; your branch is not touched.' : `Moves ${info.branch} to the integration commit. Your working tree is checked first, no repository hooks run and nothing is pushed.`;
    $('#confirm-attempt').textContent = `${task.title} / commit ${task.attempt_id}`;
    $('#confirm-control').textContent = discard ? 'Confirm discard' : 'Confirm fast-forward';
    return new Promise(resolve=>{dialog.addEventListener('close',()=>{confirmPending=false;resolve(dialog.returnValue==='confirm');},{once:true});dialog.showModal();});
  }
  $('#confirm-title').textContent = action==='kill'?'Kill this attempt?':'Stop this task?';
  $('#confirm-description').textContent = action==='kill' ? (simulation()?'Immediately revoke this simulated attempt. There is no operating-system process to kill.':'Immediately terminate the entire attempt process tree. Uncommitted work may be lost.') : 'Request cancellation of this task. Active work waits for acknowledgement; queued work is cancelled before dispatch.';
  $('#confirm-attempt').textContent = `${task.title} / attempt ${task.attempt_id||'not dispatched'}`;
  $('#confirm-control').textContent = action==='kill'?'Confirm kill':'Confirm stop';
  return new Promise(resolve=>{dialog.addEventListener('close',()=>{confirmPending=false;resolve(dialog.returnValue==='confirm');},{once:true});dialog.showModal();});
}
async function copyText(text) {
  try { if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable'); await navigator.clipboard.writeText(text);toast('Copied full text.'); }
  catch (_) { $('#copy-text').value=text;$('#copy-dialog').showModal();$('#copy-text').select(); }
}
document.addEventListener('click',async e=>{
  const close = e.target.closest('[data-close]'); if (close) {document.getElementById(close.dataset.close).close();return;}
  const chatKey=e.target.closest('[data-chat-key]'); if (chatKey) {if (chatSocket?.readyState===1) chatSocket.send(JSON.stringify({data:(k=>typeof k==='function'?k():k)(chatKeys[Number(chatKey.dataset.chatKey)][0])})); chatTerm?.focus(); return;}
  const fill=e.target.closest('[data-ask-fill]'); if (fill) {const box=fill.closest('fieldset').querySelector('textarea'); box.value=fill.dataset.text; box.focus(); return;}
  const bsOpt=e.target.closest('[data-bs-opt]'); if (bsOpt) {bsOpt.disabled=true; await bsAnswer(bsOpt.dataset,bsOpt.dataset.text); bsOpt.disabled=false; return;}
  const bsExpand=e.target.closest('[data-bs-expand]'); if (bsExpand) {bsExpand.disabled=true; if (await command({action:'brainstorm_expand',brainstorm_id:bsExpand.dataset.bsExpand,phase:bsExpand.dataset.bsPhase})) toast('The lead is breaking the phase into tasks.'); else bsExpand.disabled=false; return;}
  const bsCreate=e.target.closest('[data-bs-create]'); if (bsCreate) {bsCreate.disabled=true; const body={action:'brainstorm_create_tasks',brainstorm_id:bsCreate.dataset.bsCreate,phase:bsCreate.dataset.bsPhase}; let r=await command(body); if (r&&r.warning) r=confirm(`${r.warning}\n\nStart anyway?`)?await command({...body,force:true}):null; if (r) toast(`Queued ${Object.keys(r.task_ids).length} tasks.`); else bsCreate.disabled=false; return;}
  const bsStop=e.target.closest('[data-bs-stop]'); if (bsStop) {if (confirm('Stop this brainstorm? Its agents stop; nothing is created.')) await command({action:'brainstorm_stop',brainstorm_id:bsStop.dataset.bsStop}); return;}
  if (e.target.closest('#bs-recommend')) {bsRecommend(); return;}
  const chatTab=e.target.closest('[data-chat-tab]'); if (chatTab) {chatConnect(chatTab.dataset.chatTab).then(chatTick);return;}
  const chatX=e.target.closest('[data-chat-close]'); if (chatX) {
    if (confirm(`Close chat ${chatTitle(chatX.dataset.chatClose)}? The agent stops; its project clone is kept.`)) {try {await chatApi({action:'chat_close',session:chatX.dataset.chatClose}); chatTick();} catch (err) {toast(err.message);}}
    return;
  }
  if (e.target.closest('#chat-attach')) {$('#chat-image').click();return;}
  const paletteOption=e.target.closest('[data-command-index]'); if (paletteOption) {await runCommand(Number(paletteOption.dataset.commandIndex));return;}
  const stat=e.target.closest('[data-task-group]'); if (stat) {showTaskGroup(stat.dataset.taskGroup);return;}
  const nav = e.target.closest('[data-view]'); if (nav) {navigateView(nav.dataset.view);return;}
  const proj = e.target.closest('[data-project]'); if (proj) {project=proj.dataset.project;eventTask='all';render();return;}
  const more = e.target.closest('[data-more-column]'); if (more) {columnLimits[Number(more.dataset.moreColumn)]+=12;render();return;}
  if (e.target.closest('#more-events')) {eventLimit=Math.min(1000,eventLimit+100);render();return;}
  const tab = e.target.closest('[data-detail-tab]'); if (tab) {detailTab=tab.dataset.detailTab;updateDetail(true);return;}
  const copy = e.target.closest('[data-copy-artifact]'); if (copy) {const task=taskDetail?.task?.id===copy.dataset.copyTask?taskDetail.task:snapshot.tasks.find(t=>t.id===copy.dataset.copyTask);const artifact=task?.artifacts.find(a=>a.id===copy.dataset.copyArtifact);if(artifact?.content!==undefined)await copyText(artifact.content);return;}
  if(e.target.closest('[data-copy-merge]')) {const task=currentTask();if(task&&typeof task.result_ref==='string'&&/^refs\/axon\/attempts\/[a-zA-Z0-9][a-zA-Z0-9._/-]*$/.test(task.result_ref)&&!task.result_ref.includes('..'))await copyText(`git merge -- ${task.result_ref}`);return;}
  const opt = e.target.closest('[data-answer-option]'); if (opt) {
    const task=currentTask(), text=task?.pending?.options?.[Number(opt.dataset.answerOption)]; if (!task||!connected||text===undefined) return;
    opt.disabled=true; const result=await taskCommand('answer',{text,pending_id:task.pending.id});
    if (result) toast('Answer sent.'); opt.disabled=false; return;
  }
  const follow = e.target.closest('[data-continue]'); if (follow) {const source=snapshot.tasks.find(t=>t.id===follow.dataset.continue);if(connected&&source){$('#detail-dialog').close();openTaskForm(source);}return;}
  if (e.target.closest('[data-new-task]')||e.target.closest('#new-task')) {if(connected)openTaskForm();return;}
  const taskButton = e.target.closest('[data-task]'); if (taskButton) {await openTaskDetail(taskButton.dataset.task,taskButton.hasAttribute('data-open-output'));return;}
  const promo = e.target.closest('[data-promote]'); if (promo) {
    if (!connected||promo.disabled) return;
    const i=(snapshot.integration||[]).find(x=>x.project_id===promo.dataset.promote); if (!i) return;
    if (!await confirmControl('promote',{title:`${i.project_id}: ${i.tasks.length} task${i.tasks.length===1?'':'s'}`,attempt_id:(i.commit||'').slice(0,10)},i)) return;
    promo.disabled=true;
    const result=await command({action:'promote_integration',project_id:i.project_id,commit:i.commit});
    if (result) toast(result.message||'Branch fast-forwarded.');
    promo.disabled=false; return;
  }
  const discardBtn = e.target.closest('[data-discard]'); if (discardBtn) {
    if (!connected||discardBtn.disabled) return;
    const i=(snapshot.integration||[]).find(x=>x.project_id===discardBtn.dataset.discard); if (!i) return;
    if (!await confirmControl('discard',{title:`${i.project_id}: ${i.tasks.length} task${i.tasks.length===1?'':'s'}`,attempt_id:(i.commit||'').slice(0,10)},i)) return;
    discardBtn.disabled=true;
    const result=await command({action:'discard_integration',project_id:i.project_id,commit:i.commit});
    if (result) toast(result.message||'Integration branch discarded.');
    discardBtn.disabled=false; return;
  }
  const verifyInt = e.target.closest('[data-verify-integration]'); if (verifyInt) {
    if (!connected||verifyInt.disabled) return;
    verifyInt.disabled=true;
    const result=await command({action:'verify_integration',project_id:verifyInt.dataset.verifyIntegration});
    if (result) toast(result.message||'Running every check.');
    verifyInt.disabled=false; return;
  }
  const reviewInt = e.target.closest('[data-review-integration]'); if (reviewInt) {
    if (!connected||reviewInt.disabled) return;
    reviewInt.disabled=true;
    const result=await command({action:'review_integration',project_id:reviewInt.dataset.reviewIntegration,agent:reviewInt.dataset.agent||'claude'});
    if (result) toast(result.duplicate?'A matching review is already queued.':'Review queued; the verdict appears here when it finishes.');
    reviewInt.disabled=false; return;
  }
  const control = e.target.closest('[data-action]');
  if (control) {
    const task = currentTask(); if (!task||!connected) return;
    const action = control.dataset.action;
    const captured = {task_id:task.id,attempt_id:task.attempt_id,pending_id:task.pending?.id};
    if (['stop','kill'].includes(action)&&!await confirmControl(action,task)) return;
    if (action==='apply'&&!confirm(`Write the changes of “${task.title}” into ${snapshot.projects.find(p=>p.id===task.project_id)?.path||'the project folder'}? They arrive as uncommitted edits; nothing is written if your own edits touch the same lines.`)) return;
    control.disabled = true;
    const result = await command({action,...captured});
    if (result) toast(result.message||(result.task_id&&action==='revise'?(result.duplicate?'That revision is already queued.':`Revision queued as task ${result.task_id}.`):result.expired?'Request expired; task blocked.':'Control accepted by runtime.'));
    control.disabled = false;
  }
});
$('#detail-dialog').addEventListener('close',()=>{selectedTask=null;taskDetail=null;detailSignature='';});
$('#add-project').onclick = ()=>{if(!connected)return;$('#project-form').reset();$('#project-form .form-error').textContent='';$('#project-description').textContent=simulation()?'Creates a simulation-only project.':'Add a project through the active runtime. Repository access is granted only by that runtime.';$('#project-path-field').hidden=simulation();$('#folder-picker').hidden=true;$('#project-dialog').showModal();};
async function browse(path){
  try{
    const r=await api('/api/command',{action:'browse_dir',path});
    $('#picker-path').textContent=r.path;$('#picker-path').dataset.path=r.path;$('#picker-up').disabled=!r.parent;$('#picker-up').dataset.path=r.parent||'';
    $('#picker-note').textContent=r.git?'Git repository':'Not a Git repository root';$('#picker-use').disabled=!r.git;
    $('#picker-list').innerHTML=r.dirs.map(d=>`<li><button type="button" data-dir="${escapeHTML(d.name)}">${escapeHTML(d.name)}${d.git?'<span class="badge">GIT</span>':''}</button></li>`).join('')||'<li class="muted" style="padding:8px 12px">No subfolders</li>';
  }catch(err){$('#project-form .form-error').textContent=err.message;}
}
$('#browse-path').onclick = ()=>{$('#folder-picker').hidden=false;browse($('#project-form [name=path]').value.trim());};
$('#picker-up').onclick = e=>browse(e.currentTarget.dataset.path);
$('#picker-list').onclick = e=>{const b=e.target.closest('[data-dir]');if(b)browse($('#picker-path').dataset.path.replace(/\/$/,'')+'/'+b.dataset.dir);};
$('#picker-use').onclick = ()=>{const f=$('#project-form'),p=$('#picker-path').dataset.path;f.path.value=p;if(!f.name.value)f.name.value=p.split('/').pop().replace(/[^A-Za-z0-9._-]/g,'-').replace(/^[._-]+/,'').slice(0,60);$('#folder-picker').hidden=true;};
$('#refresh').onclick = ()=>poll();
$('#pause').onclick = async ()=>{if(!snapshot)return;const result=await command({action:snapshot.paused?'resume':'pause'});if(result)toast(snapshot.paused?'Dispatch paused. Active attempts continue.':'Dispatch resumed.');};
$('#notifications').hidden = !('Notification' in window);
$('#notifications').onclick = async ()=>{
  if (!('Notification' in window)) return;
  try {const permission=await Notification.requestPermission();toast(permission==='granted'?'Notifications enabled while this page stays open.':'Notifications unavailable. The tab title still shows waiting tasks.');}
  catch (_) {toast('Notifications unavailable in this browser.');}
};
$('#task-project').onchange = ()=>{populateSources();syncFlowRow();};
$('#task-form').onsubmit = async e=>{
  e.preventDefault();if(!connected)return;
  const form=e.currentTarget, button=form.querySelector('[type="submit"]');button.disabled=true;
  const fields=Object.fromEntries(new FormData(form));
  delete fields.checks; const ticked=[...form.querySelectorAll('input[name="checks"]:checked')].map(i=>i.value); if(ticked.length)fields.checks=ticked;
  fields.title=(fields.title||'').trim()||(fields.spec||'').trim().split('\n')[0].slice(0,120); fields.scope=(fields.scope||'').trim()||'.';
  if(fields.source_task_id)fields.source_attempt_id=$('#task-source').selectedOptions[0]?.dataset.attempt;
  try {const result=await api('/api/command',{action:'create_task',...fields});$('#task-dialog').close();await poll();toast(result.duplicate?'Matching task already exists; opening it.':simulation()?'Task queued for simulation.':'Task queued.');selectedTask=result.task_id;taskDetail=null;detailTab=simulation()?'results':'log';updateDetail(true);$('#detail-dialog').showModal();await loadTaskDetail(selectedTask);}
  catch(err){form.querySelector('.form-error').textContent=err.message;}finally{button.disabled=false;}
};
$('#project-form').onsubmit = async e=>{
  e.preventDefault();if(!connected)return;
  const form=e.currentTarget,button=form.querySelector('[type="submit"]');button.disabled=true;
  try{const fields=Object.fromEntries(new FormData(form));const result=await api('/api/command',{action:'create_project',...fields});project=result.id;$('#project-dialog').close();await poll();toast(simulation()?'Simulation project added.':'Project added by runtime.');}
  catch(err){form.querySelector('.form-error').textContent=err.message;}finally{button.disabled=false;}
};
$('#content').addEventListener('submit',async e=>{
  if(e.target.id==='agent-options-form'){
    e.preventDefault();if(!connected)return;
    const form=e.target,button=form.querySelector('[type="submit"]');button.disabled=true;
    try{for(const agent of Object.keys(snapshot.agent_options||{})){const f=new FormData(form);await api('/api/command',{action:'set_agent_options',agent,model:f.get(`${agent}_model`)||'',effort:f.get(`${agent}_effort`)||''});}await poll();toast('Model and effort saved. New attempts use them.');}
    catch(err){form.querySelector('.form-error').textContent=err.message;}
    finally{button.disabled=false;}
    return;
  }
  if(e.target.id!=='settings-form')return;
  e.preventDefault();if(!connected)return;
  const form=e.target,button=form.querySelector('[type="submit"]');button.disabled=true;
  try{await api('/api/command',{action:'update_settings',values:Object.fromEntries(new FormData(form))});await poll();toast('Runtime settings saved.');}
  catch(err){form.querySelector('.form-error').textContent=err.message;}
  finally{button.disabled=false;}
});
$('#task-detail').addEventListener('submit',async e=>{
  e.preventDefault();const form=e.target,button=form.querySelector('[type="submit"]');if(!button)return;
  button.disabled=true;const task=currentTask();if(!task)return;
  const multi=form.classList.contains('multi-ask'), kind=multi||form.id==='answer-form'?'answer':'instruction';
  const result=await taskCommand(kind,{text:multi?multiAnswerText(form):new FormData(form).get(kind),pending_id:task.pending?.id});
  if(result){toast('Saved for this attempt.');form.reset();}button.disabled=false;
});
$('#content').addEventListener('input',e=>{if(e.target.id==='task-search'){search=e.target.value;render();}});
$('#content').addEventListener('change',e=>{
  if(e.target.id==='group-filter')taskGroup=e.target.value;
  else if(e.target.id==='state-filter')stateFilter=e.target.value;
  else if(e.target.id==='event-task')eventTask=e.target.value;
  else if(e.target.id==='event-type')eventType=e.target.value;
  else return;render();
});
$('#task-detail').addEventListener('keydown',e=>{
  if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key)||!e.target.matches('[role="tab"]'))return;
  const tabs=[...$('#task-detail').querySelectorAll('[role="tab"]')],index=tabs.indexOf(e.target);
  const next=e.key==='Home'?0:e.key==='End'?tabs.length-1:(index+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;
  e.preventDefault();tabs[next].focus();tabs[next].click();
});
$('#open-command').onclick=()=>openCommands();
$('#command-search').addEventListener('input',()=>renderCommands(true));
$('#command-search').addEventListener('keydown',e=>{
  if (e.key==='ArrowDown'||e.key==='ArrowUp') {e.preventDefault();selectCommand(commandIndex+(e.key==='ArrowDown'?1:-1),e.key==='ArrowDown'?1:-1,true);}
  else if (e.key==='Enter') {e.preventDefault();runCommand(commandIndex);}
});
document.addEventListener('keydown',e=>{
  if (e.repeat) return;
  if ((e.ctrlKey||e.metaKey)&&!e.altKey&&e.key.toLowerCase()==='k') {
    if ($('#command-dialog').open) {e.preventDefault();$('#command-dialog').close();}
    else if (!document.querySelector('dialog[open]')) {e.preventDefault();openCommands();}
    return;
  }
  if (!e.altKey||e.ctrlKey||e.metaKey||e.shiftKey||document.querySelector('dialog[open]')||e.target.closest('input, textarea, select, [contenteditable]')) return;
  if (e.key.toLowerCase()==='n'&&connected) {e.preventDefault();openTaskForm();}
  else if (/^[1-7]$/.test(e.key)&&snapshot) {e.preventDefault();navigateView(Object.keys(names)[Number(e.key)-1]);$('#page-title').focus({preventScroll:true});}
});

// Brainstorm: Claude and Codex ask you, plan alone, compare, merge and check; the plan becomes tasks only when you press the button.
const bsPhases = ['clarify','draft','compare','merge','check','ready'];
// Heavy = draft, compare, merge; light = the steps that only ask and check.
const bsRecommended = {claude:{model:'claude-opus-5-5',effort:'high',light_model:'claude-sonnet-5-5',light_effort:'medium'},codex:{model:'gpt-6-astra',effort:'high',light_model:'gpt-6.1-sol',light_effort:'medium'}};
const bsAgentName = a => ({claude:'Claude Code',codex:'Codex'}[a]||a);
function bsFields(role,label,agent) {
  const models=((snapshot.agent_options||{})[agent]||{}).models||[];
  return `<fieldset><legend>${label}</legend><div class="form-row">${[['model','Model'],['effort','Effort'],['light_model','Model, asking and checking'],['light_effort','Effort, asking and checking']].map(([k,l])=>`<label>${l}<input name="${role}_${k}" ${k.endsWith('model')?`list="bs-models-${escapeHTML(agent)}"`:''} maxlength="80" placeholder="default" autocomplete="off"></label>`).join('')}</div></fieldset>`;
}
function brainstormPanel() {
  const agents=['claude','codex'], opts=sel=>agents.map(a=>`<option value="${a}" ${a===sel?'selected':''}>${bsAgentName(a)}</option>`).join('');
  const lists=agents.map(a=>`<datalist id="bs-models-${a}">${(((snapshot.agent_options||{})[a]||{}).models||[]).map(m=>`<option value="${escapeHTML(m)}">`).join('')}</datalist>`).join('');
  return `<section class="panel" id="bs-root"><form id="bs-start"><label>Project<select name="project_id">${snapshot.projects.map(p=>`<option value="${escapeHTML(p.id)}" ${project===p.id?'selected':''}>${escapeHTML(p.name)}</option>`).join('')}</select></label><label>Goal<textarea name="goal" required maxlength="8000" rows="4" placeholder="What should be built or changed? The agents ask you whatever they need to know; they never guess."></textarea></label><div class="form-row"><label>Lead: asks first, writes the merged plan<select name="lead">${opts('claude')}</select></label><label>Other: second planner, checks the plan<select name="other">${opts('codex')}</select></label></div><details><summary>Model and effort for this brainstorm</summary>${bsFields('lead','Lead','claude')}${bsFields('other','Other','codex')}${lists}<button class="button secondary" type="button" id="bs-recommend">Fill in the suggested values for these two agents</button><p class="muted">Blank = your Agents settings. Model and effort for the main steps (draft, compare, merge) and for the light ones (asking, checking).</p></details><p class="muted">Both agents work read-only: they ask you questions, each drafts a plan alone, they compare, one merges, the other checks. About 7 short runs per agent, more if they ask more. Nothing is built until you create the tasks from the finished plan.</p><p class="form-error" role="alert"></p><button class="button primary" type="submit">Start brainstorm</button></form></section><div id="bs-list"></div>`;
}
function bsRecommend() {
  const f=$('#bs-start'); if (!f) return;
  for (const role of ['lead','other']) { const r=bsRecommended[f[role].value]||{}; for (const [k,v] of Object.entries(r)) f[`${role}_${k}`].value=v; }
}
// Several questions in one ask: each has its own choices (a click fills its box) and a box to type in; one send for all.
function multiAsk(qs, attrs) {
  return `<form class="multi-ask" ${attrs}>${qs.map((q,i)=>`<fieldset class="ask-q"><legend>${i+1}) ${escapeHTML(q.question)}</legend>${(q.from||[]).length?`<details class="ask-from"><summary>asked by ${(q.from||[]).length>1?'both agents':'one agent'}: the original wording</summary><ul>${q.from.map(x=>`<li>${escapeHTML(x)}</li>`).join('')}</ul></details>`:''}${(q.options||[]).length?`<div class="answer-options" role="group" aria-label="Choices for question ${i+1}">${q.options.map(o=>`<button type="button" class="button secondary" data-ask-fill data-text="${escapeHTML(o)}">${escapeHTML(o)}</button>`).join('')}</div>`:''}<textarea name="a${i}" required maxlength="450" rows="2" aria-label="Your answer to question ${i+1}"></textarea></fieldset>`).join('')}<button class="button primary" type="submit">Send all answers →</button></form>`;
}
const multiAnswerText = form => [...form.querySelectorAll('textarea')].map((t,i)=>`${i+1}) ${t.value.trim()}`).join('\n');
function brainstormCard(b) {
  const at=bsPhases.indexOf(b.phase), plan=b.plan;
  const steps=bsPhases.map((p,i)=>`<li class="${i===at?'current':i<at?'past':''}">${p}</li>`).join('');
  const collecting=b.collecting?'<p class="muted">Collecting questions from both agents, so that you answer each thing once …</p>':'';
  const asks=collecting+(b.questions||[]).map(q=>{const d=`data-q-task="${escapeHTML(q.task_id)}" data-q-attempt="${escapeHTML(q.attempt_id)}" data-q-pending="${escapeHTML(q.pending_id)}"`;
    if (q.gate) return `<section class="request-box"><h3>Both agents ask you (their questions merged: each thing once)</h3>${multiAsk(q.questions,`data-q-gate="${escapeHTML(b.id)}"`)}</section>`;
    if ((q.questions||[]).length) return `<section class="request-box"><h3>${escapeHTML(bsAgentName(q.agent))} asks you</h3>${multiAsk(q.questions,d)}</section>`;
    return `<section class="request-box"><h3>${escapeHTML(bsAgentName(q.agent))} asks you</h3><p>${escapeHTML(q.question)}</p>${(q.options||[]).length?`<div class="answer-options" role="group" aria-label="Choose an answer">${q.options.map(o=>`<button type="button" class="button secondary" data-bs-opt ${d} data-text="${escapeHTML(o)}">${escapeHTML(o)}</button>`).join('')}</div><p class="field-help">Or write your own answer:</p>`:''}<form class="bs-answer" ${d}><textarea name="text" data-bs-text="${escapeHTML(q.task_id)}" required maxlength="2000" rows="2" aria-label="Your answer"></textarea><button class="button primary" type="submit">Send answer →</button></form></section>`;}).join('');
  const qa=(b.qa||[]).length?`<details><summary>Your answers so far (${b.qa.length})</summary><ul class="queue-reasons">${b.qa.map(x=>`<li><strong>${escapeHTML(bsAgentName(x.by))}</strong> asked: ${escapeHTML(x.q)}<br><span class="muted">${escapeHTML(x.a)}</span></li>`).join('')}</ul></details>`:'';
  const body=plan?`<p>${escapeHTML(plan.summary||'')}</p>`:'';
  const act=b.status==='ACTIVE'?`<button class="button danger" data-bs-stop="${escapeHTML(b.id)}">Stop</button>`:plan?`<button class="button primary" data-view="plans">${b.status==='READY'?'Review the plan':'Follow the plan'} →</button>`:'';
  return `<section class="panel bs-card"><div class="panel-header"><h2>#${escapeHTML(b.id)} ${escapeHTML(b.goal.trim().split('\n')[0].slice(0,120))}</h2>${badge(b.status)}</div><p class="muted">${escapeHTML(b.project_id)} / lead ${escapeHTML(bsAgentName(b.agents.lead))}, other ${escapeHTML(bsAgentName(b.agents.other))}</p><ol class="bs-steps" aria-label="Phase">${steps}</ol>${b.why?`<p class="form-error">${escapeHTML(b.why)}</p>`:''}${asks}${qa}${body}<div class="detail-actions">${act}</div></section>`;
}
function bsRefresh() {
  const list=$('#bs-list'); if (!list) return;
  const items=(snapshot.brainstorms||[]).filter(b=>project==='all'||b.project_id===project), sig=JSON.stringify(items);
  if (list.dataset.sig===sig) return;
  const typed=Object.fromEntries([...list.querySelectorAll('[data-bs-text]')].map(t=>[t.dataset.bsText,t.value]));
  list.dataset.sig=sig; list.innerHTML=items.map(brainstormCard).join('')||`<section class="panel">${empty('No brainstorms yet','Start one above.')}</section>`;
  list.querySelectorAll('[data-bs-text]').forEach(t=>{t.value=typed[t.dataset.bsText]||'';});
}
async function bsAnswer(d,text) {
  const r=await command({action:'answer',task_id:d.qTask,attempt_id:d.qAttempt,pending_id:d.qPending,text}); if (r) toast('Answer sent.');
}
$('#content').addEventListener('submit', async e => {
  if (e.target.id==='bs-start') {
    e.preventDefault(); const button=e.target.querySelector('[type="submit"]'), err=e.target.querySelector('.form-error'); button.disabled=true; err.textContent='';
    try {const r=await api('/api/command',{action:'brainstorm_start',...Object.fromEntries(new FormData(e.target))}); e.target.goal.value=''; toast(`Brainstorm ${r.brainstorm_id} started.`); await poll();}
    catch (x) {err.textContent=x.message;} finally {button.disabled=false;}
  } else if (e.target.classList?.contains('multi-ask') && e.target.dataset.qGate) {
    e.preventDefault(); const button=e.target.querySelector('[type="submit"]'); button.disabled=true;
    const r=await command({action:'brainstorm_answer',brainstorm_id:e.target.dataset.qGate,answers:[...e.target.querySelectorAll('textarea')].map(t=>t.value.trim())});
    if (r) toast('Answers sent to both agents.'); else button.disabled=false;
  } else if (e.target.classList?.contains('multi-ask') && e.target.dataset.qTask) {
    e.preventDefault(); const button=e.target.querySelector('[type="submit"]'); button.disabled=true; await bsAnswer(e.target.dataset,multiAnswerText(e.target)); button.disabled=false;
  } else if (e.target.classList?.contains('bs-answer')) {
    e.preventDefault(); const box=e.target.querySelector('textarea'); await bsAnswer(e.target.dataset,box.value.trim()); box.value='';
  }
});
// Plans: a finished brainstorm followed task by task. The lanes come from the real tasks the plan created; PLAN.md is for you, plan.json for an agent.
const planLanes = {todo:'To do',doing:'In progress',done:'Done',stuck:'Stuck'};
const planLane = task => !task ? 'todo' : task.state==='COMPLETED' ? 'done' : ['FAILED','CANCELLED','BLOCKED'].includes(task.state) ? 'stuck' : active.includes(task.state) ? 'doing' : 'todo';
function plansView() {
  const items=(snapshot.brainstorms||[]).filter(b=>b.plan&&(project==='all'||b.project_id===project));
  return items.map(planCard).join('')||`<section class="panel">${empty('No plans yet','A finished Brainstorm shows up here.')}</section>`;
}
function planCard(b) {
  const plan=b.plan, made=b.created||{}, byID=Object.fromEntries(snapshot.tasks.map(t=>[t.id,t]));
  const all=plan.phases.flatMap(ph=>ph.tasks.map(pt=>({pt,task:byID[made[pt.id]]}))), done=all.filter(c=>planLane(c.task)==='done').length;
  const item=({pt,task})=>`<div class="plan-item"><strong>${escapeHTML(pt.id)}</strong> ${escapeHTML(pt.title)}<br><span class="muted">${escapeHTML(pt.agent)}, scope ${escapeHTML((pt.scope||[]).join(', ')||'-')}${[].concat(pt.after||[]).length?`, after ${escapeHTML([].concat(pt.after).join(', '))}`:''}</span>${task?`<br>${badge(task.state)} <button class="text-button" data-task="${escapeHTML(task.id)}">task ↗</button>`:''}<details><summary>Done when</summary><ul class="queue-reasons">${(pt.acceptance||[]).map(x=>`<li>${escapeHTML(x)}</li>`).join('')}</ul></details><details><summary>What the agent is given</summary><pre class="bs-brief">${escapeHTML(pt.brief||'')}</pre></details></div>`;
  const phase=ph=>{
    const cards=ph.tasks.map(pt=>({pt,task:byID[made[pt.id]]}));
    const lanes=cards.length?`<div class="plan-board">${Object.entries(planLanes).map(([l,label])=>{const mine=cards.filter(c=>planLane(c.task)===l);return `<div class="plan-lane"><h3>${label} <small>${mine.length}</small></h3>${mine.map(item).join('')}</div>`;}).join('')}</div>`:'';
    const act=ph.expanding?`<p class="muted">The lead is breaking this phase into tasks … <button class="text-button" data-bs-stop="${escapeHTML(b.id)}">Stop</button></p>`
      :ph.started?(ph.failed?`<button class="button primary" data-bs-create="${escapeHTML(b.id)}" data-bs-phase="${escapeHTML(ph.id)}">Retry phase ${escapeHTML(ph.id)}: make the ${ph.failed} failed or stopped task${ph.failed>1?'s':''} again</button>`:'')
      :!ph.ready?'':ph.tasks.length?`<button class="button primary" data-bs-create="${escapeHTML(b.id)}" data-bs-phase="${escapeHTML(ph.id)}">Start phase ${escapeHTML(ph.id)}: create these ${ph.tasks.length} tasks</button>`
      :`<button class="button primary" data-bs-expand="${escapeHTML(b.id)}" data-bs-phase="${escapeHTML(ph.id)}">Break phase ${escapeHTML(ph.id)} into tasks</button>`;
    const state=ph.done?'COMPLETED':ph.started?'RUNNING':ph.ready?'READY':'QUEUED';
    return `<section class="plan-phase"><div class="panel-header"><h3>Phase ${escapeHTML(ph.id)}: ${escapeHTML(ph.title)}</h3>${badge(state)}</div><p>${escapeHTML(ph.objective||'')}</p>${(ph.done_when||[]).length?`<details><summary>Phase done when</summary><ul class="queue-reasons">${ph.done_when.map(x=>`<li>${escapeHTML(x)}</li>`).join('')}</ul></details>`:''}${lanes}<div class="detail-actions">${act}</div></section>`;
  };
  const files=b.files?.human?`<p class="muted">For you: <code>${escapeHTML(b.files.human)}</code><br>For an agent: <code>${escapeHTML(b.files.ai)}</code></p>`:'';
  let extra=b.expand_error?`<p class="form-error">${escapeHTML(b.expand_error)}</p>`:'';
  if ((plan.disagreements||[]).length) extra+=`<h3>They disagree: you decide</h3><ul class="queue-reasons">${plan.disagreements.map(x=>`<li><strong>${escapeHTML(x.topic)}</strong><br>Claude: ${escapeHTML(x.claude)}<br>Codex: ${escapeHTML(x.codex)}</li>`).join('')}</ul>`;
  if ((plan.risks||[]).length) extra+=`<h3>Risks</h3><ul class="queue-reasons">${plan.risks.map(r=>`<li>${escapeHTML(r)}</li>`).join('')}</ul>`;
  if (b.objections) extra+=`<div class="review-callout"><strong>The checker still objects</strong><span>${escapeHTML(b.objections).replaceAll('\n','<br>')}</span></div>`;
  const phasesDone=plan.phases.filter(ph=>ph.done).length, state=phasesDone===plan.phases.length?'COMPLETED':b.status==='READY'&&!plan.phases.some(ph=>ph.started)?'READY':'RUNNING';
  return `<section class="panel bs-card"><div class="panel-header"><h2>#${escapeHTML(b.id)} ${escapeHTML(b.goal.trim().split('\n')[0].slice(0,120))}</h2>${badge(state)}</div><p class="muted">${escapeHTML(b.project_id)}: ${done} / ${all.length} written tasks done, ${phasesDone} / ${plan.phases.length} phases</p><meter min="0" max="${all.length||1}" value="${done}" aria-label="Tasks done"></meter><p>${escapeHTML(plan.summary||'')}</p>${files}${extra}${plan.phases.map(phase).join('')}</section>`;
}
// Chat: a real terminal (xterm.js, loaded on first use) on the agent's tmux session over a WebSocket.
let chatSession = '', chatTerm = null, chatFit = null, chatSocket = null, chatLoading = null;
// For phones and keys the browser keeps: each button types its terminal sequence.
// A wheel click in the middle of the terminal: apps like Codex ignore one at the corner (1,1).
const chatWheel = up => `\x1b[<${up?64:65};${(chatTerm?.cols||80)>>1};${(chatTerm?.rows||24)>>1}M`;
const chatKeys = [['\x1b','Esc'],['\t','Tab'],['\x1b[Z','⇧Tab'],['\x1b[A','↑'],['\x1b[B','↓'],['\x1b[D','←'],['\x1b[C','→'],['\x1b[1;2A','⇧↑'],['\x1b[1;2B','⇧↓'],['\x1b[1;2D','⇧←'],['\x1b[1;2C','⇧→'],['\r','Enter'],['\n','New line'],[()=>chatWheel(true),'Scroll ▲'],[()=>chatWheel(false),'Scroll ▼'],['\x03','Ctrl-C'],['\x04','Ctrl-D']];
const chatApi = body => api('/api/command', body);
function chatPanel() {
  return `<section class="panel" id="chat-root"><form id="chat-start" class="chat-bar"><select name="project_id" aria-label="Project">${snapshot.projects.map(p=>`<option value="${escapeHTML(p.id)}" ${project===p.id?'selected':''}>${escapeHTML(p.name)}</option>`).join('')}</select><select name="agent" aria-label="Agent"><option value="claude">Claude Code</option><option value="codex">Codex</option><option value="shell">Shell (bash)</option></select><input name="label" maxlength="20" pattern="[A-Za-z0-9]{1,20}" placeholder="name (optional)" aria-label="Chat name, optional; a new name opens a separate chat"><button class="button primary" type="submit">Start or open chat</button></form><div id="chat-tabs" class="chat-tabs" role="tablist" aria-label="Running chats"></div><div id="chat-term" class="chat-term" aria-label="Agent terminal. Typing here goes to the agent.">Start a chat, or pick a running one.</div><div class="chat-bar chat-keys">${chatKeys.map(([,l],i)=>`<button class="button secondary" type="button" data-chat-key="${i}">${l}</button>`).join('')}<button class="button secondary" type="button" id="chat-attach">Image…</button><input id="chat-image" type="file" accept="image/png,image/jpeg,image/gif,image/webp" hidden></div><p class="muted chat-hint">Click the terminal and type, as in any terminal. Drag to select = copy; Ctrl+Shift+V = paste; the wheel scrolls back. Paste or drop an image to attach it. Chats are not sandboxed: the agent runs as you, in the project folder itself. Swipe the terminal (or use Scroll ▲▼) to go back through the history. From a terminal: <code>axon chat</code>.</p></section>`;
}
const chatTitle = n => n.replace(/^axon-chat-/, '');
function chatTabs(sessions) {
  const sig = sessions.join('|') + '#' + chatSession, tabs = $('#chat-tabs');
  if (!tabs || tabs.dataset.sig === sig) return;
  tabs.dataset.sig = sig;
  tabs.innerHTML = sessions.map(n=>`<span class="chat-tab ${n===chatSession?'active':''}"><button type="button" role="tab" aria-selected="${n===chatSession}" data-chat-tab="${escapeHTML(n)}">${escapeHTML(chatTitle(n))}</button><button type="button" data-chat-close="${escapeHTML(n)}" aria-label="Close chat ${escapeHTML(chatTitle(n))}">×</button></span>`).join('') || '<span class="muted">No chats running.</span>';
}
async function chatTick() {
  if (view!=='chat'||!$('#chat-root')) return;
  try {
    const {sessions} = await chatApi({action:'chat_list'});
    if (!sessions.includes(chatSession) || !chatSocket) chatConnect(sessions.includes(chatSession) ? chatSession : sessions[0] || '');
    chatTabs(sessions);
  } catch (err) {toast(err.message);}
}
function loadScript(src) {
  return new Promise((ok, fail) => {const s=document.createElement('script'); s.src=src; s.onload=ok; s.onerror=()=>fail(new Error(`Could not load ${src}`)); document.head.append(s);});
}
function chatDisconnect() {const ws=chatSocket; chatSocket=null; ws?.close(); chatTerm?.dispose(); chatTerm=null;}
// On a phone the box fits ~40 columns and the agent's UI cuts its lines short. Keep at least 80 columns
// and let the box pan sideways (a horizontal swipe), the way a desktop terminal would just be wider.
const chatNarrow = matchMedia('(max-width: 700px)'), CHAT_MIN_COLS = 80;
function chatFitTo(term) {
  const d = chatFit.proposeDimensions();
  if (d) term.resize(Math.max(d.cols, CHAT_MIN_COLS), d.rows);
}
async function chatConnect(name) {
  const box = $('#chat-term'); if (!box) return;
  if (name === chatSession && chatSocket) return;
  chatDisconnect(); chatSession = name;
  if (!name) {box.textContent = 'Start a chat, or pick a running one.'; return;}
  try {
    chatLoading ||= (async()=>{const l=document.createElement('link'); l.rel='stylesheet'; l.href='/xterm.css'; document.head.append(l); await loadScript('/xterm.js'); await loadScript('/addon-fit.js');})();
    await chatLoading;
  } catch (err) {chatLoading=null; box.textContent=err.message; return;}
  if (chatSession !== name || chatSocket) return;  // switched again while loading
  box.textContent = '';
  const term = chatTerm = new Terminal({fontSize:chatNarrow.matches?11:13, cursorBlink:true, scrollback:0, macOptionIsMeta:true, fontFamily:'ui-monospace, "JetBrains Mono", Menlo, Consolas, monospace', theme:{background:'#050505', foreground:'#e6e6e6', cursor:'#ff3b3b', selectionBackground:'#ff3b3b55'}});
  chatFit = new FitAddon.FitAddon(); term.loadAddon(chatFit); term.open(box); chatFitTo(term);
  // tmux sends what you select with the mouse as OSC 52; put it on the system clipboard like a desktop terminal.
  term.parser.registerOscHandler(52, data => {
    const b64 = data.slice(data.indexOf(';') + 1);
    if (b64 && b64 !== '?') try {navigator.clipboard?.writeText(new TextDecoder().decode(Uint8Array.from(atob(b64), c => c.charCodeAt(0)))).catch(()=>{});} catch (_) {/* not base64 */}
    return true;
  });
  new ResizeObserver(()=>{if (chatTerm===term) chatFitTo(term);}).observe(box);
  const ws = chatSocket = new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/api/chat/ws?session=${encodeURIComponent(name)}`);
  ws.binaryType = 'arraybuffer';
  const send = msg => {if (ws.readyState===1) ws.send(JSON.stringify(msg));};
  term.onData(data=>send({data}));
  term.onResize(({cols,rows})=>send({resize:[cols,rows]}));
  ws.onopen = () => {send({resize:[term.cols,term.rows]}); term.focus();};
  ws.onmessage = e => term.write(new Uint8Array(e.data));
  ws.onclose = () => {if (chatSocket===ws) {chatSocket=null; term.write('\r\n\x1b[2m[disconnected; reconnecting…]\x1b[0m\r\n'); setTimeout(chatTick, 1000);}};
}
async function chatUpload(file) {
  if (!chatSession) {toast('Start or pick a chat first.'); return;}
  if (!file || !file.type.startsWith('image/')) return;
  if (file.size > 8_000_000) {toast('The image is larger than 8 MB.'); return;}
  try {
    const response = await fetch('/api/chat/upload?session=' + encodeURIComponent(chatSession), {method:'POST', credentials:'same-origin', headers:{'Content-Type':file.type}, body:file});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Upload failed');
    toast('Image attached. Add your question and press Enter.'); chatTerm?.focus();
  } catch (err) {toast(err.message);}
}
$('#content').addEventListener('submit', async e => {
  if (e.target.id!=='chat-start') return;
  e.preventDefault(); const button=e.target.querySelector('[type="submit"]'); button.disabled=true; toast('Starting chat… the first start clones the project.');
  try {const {session}=await chatApi({action:'chat_start',...Object.fromEntries(new FormData(e.target))}); $('#chat-tabs').dataset.sig=''; await chatConnect(session); chatTick();}
  catch (err) {toast(err.message);} finally {button.disabled=false;}
});
$('#content').addEventListener('change', e => {if (e.target.id==='chat-image') {chatUpload(e.target.files[0]); e.target.value='';}});
$('#content').addEventListener('paste', e => {
  const f=[...(e.clipboardData?.files||[])].find(x=>x.type.startsWith('image/'));
  if (f && e.target.closest('#chat-term')) {e.preventDefault(); e.stopPropagation(); chatUpload(f);}
}, true);
// A swipe on the terminal is the wheel: xterm does not turn touch into scrolling, tmux scrolls its history on the wheel.
// Finger distance -> wheel clicks, with momentum after the finger lifts (like a phone's own scrolling).
const CHAT_PX_PER_CLICK = 16;  // smaller = the text moves further per swipe
let chatTouchX = 0, chatTouchY = null, chatTouchT = 0, chatVel = 0, chatPx = 0, chatFling = 0;
function chatScrollBy(dy) {  // dy > 0: finger down = back in time
  chatPx += dy;
  const n = Math.trunc(chatPx / CHAT_PX_PER_CLICK);
  if (!n || chatSocket?.readyState !== 1) return;
  chatPx -= n * CHAT_PX_PER_CLICK;
  chatSocket.send(JSON.stringify({data: chatWheel(n > 0).repeat(Math.min(Math.abs(n), 12))}));
}
$('#content').addEventListener('touchstart', e => {
  cancelAnimationFrame(chatFling); chatVel = chatPx = 0;
  chatTouchY = e.target.closest('#chat-term') ? e.touches[0].clientY : null; chatTouchX = e.touches[0].clientX; chatTouchT = e.timeStamp;
}, {passive:true});
$('#content').addEventListener('touchmove', e => {
  if (chatTouchY === null) return;
  const y = e.touches[0].clientY, dt = Math.max(1, e.timeStamp - chatTouchT);
  if (Math.abs(e.touches[0].clientX - chatTouchX) > Math.abs(y - chatTouchY) + 6) {chatTouchY = null; return;}  // sideways: the browser pans the box
  chatVel = 0.7 * chatVel + 0.3 * (y - chatTouchY) / dt;  // px per ms, smoothed
  chatScrollBy(y - chatTouchY); chatTouchY = y; chatTouchT = e.timeStamp;
  e.preventDefault();
}, {passive:false});
function chatTouchEnd(e) {
  if (chatTouchY === null) return;
  chatTouchY = null;
  if (e.timeStamp - chatTouchT > 100) return;  // held still before lifting: no fling
  let last = performance.now();
  const glide = now => {
    const dt = now - last; last = now;
    chatScrollBy(chatVel * dt); chatVel *= Math.pow(0.95, dt / 16);
    if (Math.abs(chatVel) > 0.03) chatFling = requestAnimationFrame(glide);
  };
  chatFling = requestAnimationFrame(glide);
}
$('#content').addEventListener('touchend', chatTouchEnd, {passive:true});
$('#content').addEventListener('touchcancel', chatTouchEnd, {passive:true});
$('#content').addEventListener('dragover', e => {if (e.target.closest('#chat-term')) e.preventDefault();});
$('#content').addEventListener('drop', e => {if (e.target.closest('#chat-term')) {e.preventDefault(); chatUpload([...e.dataTransfer.files].find(x=>x.type.startsWith('image/')));}});
setInterval(chatTick, 3000);
$('#login-form').onsubmit = async e=>{
  e.preventDefault(); const form=e.currentTarget, button=form.querySelector('[type="submit"]'); button.disabled=true;
  try {await api('/api/login',{password:$('#login-password').value}); form.reset(); $('#login-dialog').close(); await poll();}
  catch (err) {form.querySelector('.form-error').textContent=err.message;} finally {button.disabled=false;}
};
async function start() {
  updateSystemClock();
  if (!['127.0.0.1','localhost'].includes(location.hostname)) {$('#where-chip').lastChild.textContent=' REMOTE'; $('#where-foot').lastChild.textContent=`Remote: ${location.hostname}`;}
  if(token) {try{await api('/api/session',{});token='';}catch(_){/* Bearer fallback if an older server does not support sessions. */}}
  await poll();setInterval(poll,1500);setInterval(()=>{updateCountdowns();updateSystemClock();},1000);
}
start();
