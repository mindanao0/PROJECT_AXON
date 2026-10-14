/* Pure rendering/control checks; no browser or localhost access. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map();
const listeners = new Map();
const node = selector => {
  if (!nodes.has(selector)) nodes.set(selector,{hidden:false,textContent:'',dataset:{},addEventListener(){},querySelectorAll(){return[];},close(){},showModal(){}});
  return nodes.get(selector);
};
const context = vm.createContext({document:{querySelector:node,querySelectorAll:()=>[],addEventListener(type,callback){listeners.set(type,callback);},title:'',hidden:false},
  window:{},location:{hash:'',pathname:'/'},history:{replaceState(){}},URLSearchParams,Date,console,setTimeout(){return 0;},clearTimeout,setInterval(){},navigator:{},matchMedia:()=>({matches:false}),
  FormData: class {constructor(form){this.form=form;}*[Symbol.iterator](){yield* Object.entries(this.form.fields);}}});
let source = fs.readFileSync('axon/web/app.js','utf8');
assert(source.endsWith('start();\n'));
source = source.slice(0,-'start();\n'.length);
vm.runInContext(source,context);
vm.runInContext(`
snapshot={mode:'simulation',paused:false,projects:[],tasks:[]};
globalThis.renderers={renderDiff,queueHint,artifactBlock,detailPanel,updateAttention,countdown,paletteMatches,paletteEntries,matchesTaskGroup,operatorQueue,providerItems,providerCard,planCard,brainstormCard,multiAsk};
`,context);
const fixture = {id:'task-safe',state:'COMPLETED',spec:'<script>prompt</script>',instructions:[],artifacts:[{
  id:'artifact-safe',name:'<img src=x onerror=alert(1)>',kind:'diff',attempt_id:'attempt-safe',hash:'abc',simulated:false,
  files:[{path:'src/<script>.py',out_of_scope:true,protected:true}],
  content:'diff --git a/test b/test\n+<script>alert(1)</script>\n-removed line\n'+'long result '.repeat(1000)
}]};
const patch = context.renderers.renderDiff(fixture);
assert(!patch.includes('<script>'));
assert(patch.includes('&lt;script&gt;'));
assert(patch.includes('OUT OF SCOPE'));
assert(patch.includes('PROTECTED'));
assert(patch.includes('long result '.repeat(1000)),'Full patch must remain available');
const result = context.renderers.artifactBlock(fixture.artifacts[0],fixture,true);
assert(!result.includes('<img'));
assert(result.includes('Copy full result'));
const hint = context.renderers.queueHint({state:'QUEUED',queue_reasons:[{message:'Scope held by <img>'}]});
assert(!hint.includes('<img>'));
assert(hint.includes('&lt;img&gt;'));
vm.runInContext(`detailTab='prompt';`,context);
const prompt = context.renderers.detailPanel({...fixture,artifacts:[]});
assert(prompt.includes('No provider prompt was sent'));
assert(!prompt.includes('<script>'));
context.renderers.updateAttention(null,{tasks:[{pending:{id:'request'}}]});
assert(context.document.title.includes('(1 waiting)'));
assert.equal(context.renderers.countdown(0),'Awaiting runtime update');
assert(!source.includes('localStorage'));
// Search must match task state + title together, and cached tasks stay disabled offline.
vm.runInContext(`
  snapshot={mode:'real',paused:false,projects:[{id:'project-a',name:'Project Alpha'}],tasks:[
    {id:'task-review',title:'Review <img src=x> parser',state:'REVIEW',backend:'codex',project_id:'project-a',updated_at:10},
    {id:'task-done',title:'Finished parser',state:'COMPLETED',backend:'codex',project_id:'project-a',updated_at:9}
  ]};connected=true;
`,context);
assert.equal(context.renderers.paletteMatches('review parser')[0].id,'task-review');
assert.equal(context.renderers.paletteMatches('project alpha')[0].kind,'project');
assert.equal(context.renderers.paletteMatches('no such command xyz').length,0);
assert(context.renderers.matchesTaskGroup({state:'REVIEW'},'attention'));
assert(!context.renderers.matchesTaskGroup({state:'CANCELLED'},'completed'));
assert(!context.renderers.matchesTaskGroup({state:'COMPLETED'},'active'));
const queue=context.renderers.operatorQueue([{id:'task-"<script>',title:'<img src=x>',state:'REVIEW',updated_at:10}]);
assert(!queue.includes('<img'));
assert(queue.includes('&lt;img'));
assert(queue.includes('Inspect diff'));
vm.runInContext('connected=false;',context);
assert(context.renderers.paletteEntries().find(item=>item.id==='new').disabled);
assert(context.renderers.paletteEntries().find(item=>item.id==='task-review').disabled);
assert(!context.renderers.paletteEntries().find(item=>item.id==='refresh').disabled);
vm.runInContext(`snapshot.providers=[{id:'codex',name:'Codex <img src=x>',status:'Busy',slots_used:2,slot_limit:3,capability:'Sandboxed CLI'}];`,context);
const fleet=context.renderers.providerItems().map(context.renderers.providerCard).join('');
assert(fleet.includes('2 / 3 slots'),'Agents page must use runtime slot counts');
assert(fleet.includes('Busy'));
assert(!fleet.includes('In-process simulation'),'Real fleet must not invent a simulated worker');
assert(!fleet.includes('<img'));

vm.runInContext(`snapshot.mode='real';snapshot.tasks=[{id:'7',state:'COMPLETED'},{id:'8',state:'RUNNING'}];`,context);
const mk=id=>({id,title:'<i>'+id+'</i>',agent:'claude',scope:[],acceptance:['ok'],brief:'b'});
const board=context.renderers.planCard({id:'1',goal:'<b>g</b>',project_id:'p',status:'READY',created:{a:7,b:8},files:{human:'/x/PLAN.md',ai:'/x/plan.json'},expand_error:'',
  plan:{summary:'s',phases:[{id:'p1',title:'one',objective:'o',done_when:[],tasks:[mk('a'),mk('b'),mk('c')],started:true,done:false,ready:false,expanding:false},
                            {id:'p2',title:'two',objective:'o',done_when:[],tasks:[],started:false,done:false,ready:false,expanding:false}]}});
assert(board.includes('1 / 3 written tasks done, 0 / 2 phases'),'a plan counts its completed tasks and phases');
assert(board.includes('/x/plan.json'));
assert(!board.includes('<i>')&&!board.includes('<b>g'),'plan text is escaped');
assert(board.includes('Done <small>1')&&board.includes('In progress <small>1')&&board.includes('To do <small>1'),'tasks sit in the lane of their real state');
assert(!board.includes('data-bs-expand')&&!board.includes('data-bs-create'),'a phase that is not its turn has no button');
const turn=(extra,tasks)=>context.renderers.planCard({id:'2',goal:'g',project_id:'p',status:'READY',created:null,files:null,expand_error:'<img src=x>',
  plan:{summary:evil0,phases:[{id:'p1',title:'t',objective:'o',done_when:[evil0],tasks,started:false,done:false,ready:true,expanding:false,...extra}],disagreements:[{topic:evil0,claude:evil0,codex:evil0}],risks:[evil0]},objections:evil0});
const evil0='<img src=x onerror=alert(1)>';
assert(turn({}, []).includes('data-bs-expand="2" data-bs-phase="p1"'),'an empty phase offers to be broken into tasks');
const withTasks=turn({}, [mk('a')]);
assert(withTasks.includes('data-bs-create="2" data-bs-phase="p1"')&&!withTasks.includes('<img')&&withTasks.includes('What the agent is given'));
assert(turn({expanding:true}, []).includes('breaking this phase into tasks'));
const retry=turn({ready:false,started:true,failed:2}, [mk('a')]);
assert(retry.includes('data-bs-create="2" data-bs-phase="p1"')&&retry.includes('make the 2 failed or stopped tasks again'),'a started phase with failed tasks offers a retry');
assert(!turn({ready:false,started:true,failed:0}, [mk('a')]).includes('data-bs-create'),'a started phase with nothing failed offers nothing');
const finished=turn({ready:false,started:true,done:true,failed:0}, [mk('a')]);
assert(finished.includes('data-bs-integrate="2" data-bs-phase="p1"')&&!finished.includes('data-bs-create'),'a finished phase offers to be integrated');
assert(!turn({ready:false,started:true,done:false,failed:0}, [mk('a')]).includes('data-bs-integrate'),'an unfinished phase does not');
assert(withTasks.includes('>READY<')&&!withTasks.includes('>RUNNING<'),'written tasks that nobody started do not make the plan RUNNING');

async function controls() {
  vm.runInContext(`
    connected=true;selectedTask='task-control';
    snapshot={tasks:[{id:'task-control',attempt_id:'old-attempt'}]};
    globalThis.controls=[];
    command=async body=>{controls.push(body);return {ok:true};};
    confirmControl=()=>new Promise(resolve=>{globalThis.confirmResolve=resolve;});
  `,context);
  const button={dataset:{action:'kill'},disabled:false};
  const click={target:{closest(selector){return selector==='[data-action]'?button:null;}}};
  const waiting=listeners.get('click')(click);
  vm.runInContext("snapshot.tasks[0].attempt_id='replacement-attempt';confirmResolve(true);",context);
  await waiting;
  assert.equal(context.controls[0].attempt_id,'old-attempt','Confirmation must not target a replacement attempt');
  const cancelled=listeners.get('click')(click);
  vm.runInContext('confirmResolve(false);',context);
  await cancelled;
  assert.equal(context.controls.length,1,'Cancelled confirmation must not send a command');

  vm.runInContext(`
    globalThis.submissions=[];
    api=async(path,body)=>{submissions.push(body);return {task_id:'new-task'};};
    poll=async()=>{};updateDetail=()=>{};
    snapshot={tasks:[{id:'source-task',attempt_id:'replacement-source'}]};
  `,context);
  node('#task-source').selectedOptions=[{dataset:{attempt:'displayed-source'}}];
  const form={fields:{source_task_id:'source-task'},querySelector(){return node('submit');},querySelectorAll(){return [{value:'logic'},{value:'html'}];}};
  await node('#task-form').onsubmit({preventDefault(){},currentTarget:form});
  assert.equal(context.submissions[0].source_attempt_id,'displayed-source','Source must bind to the displayed option rather than the latest snapshot');
  assert.equal(JSON.stringify(context.submissions[0].checks),'["logic","html"]','Every ticked check is sent as a list (FormData alone keeps only the last value)');
}
// Agent model/effort settings: real mode only, escaped, current values selected.
vm.runInContext(`globalThis.aop=agentOptionsPanel; snapshot={mode:'simulation',agent_options:{claude:{model:'x',effort:'low',efforts:['low'],models:[]}}};`,context);
assert.equal(context.aop(),'','Simulation has no agent options panel');
vm.runInContext(`snapshot={mode:'real',agent_options:{
  claude:{model:'<b>x</b>',effort:'high',efforts:['low','medium','high'],models:['haiku','<i>m</i>']},
  codex:{model:'',effort:'',efforts:['low'],models:[]}}};`,context);
const panel = context.aop();
assert(!panel.includes('<b>x</b>')&&!panel.includes('<i>m</i>'),'Model names must be escaped');
assert(/<option selected>high<\/option>/.test(panel),'The configured effort is preselected');
assert(panel.includes('name="claude_model"')&&panel.includes('name="codex_effort"'),'Both agents are editable');
assert(panel.includes('<option value="">Default</option>'),'A blank means the CLI default');
// Usage panel: real mode only, escaped, honest about what the CLIs did not expose.
vm.runInContext(`globalThis.up=usagePanel; snapshot={mode:'simulation',usage:[{agent:'x',kind:'implement',attempts:1,outcomes:{done:1},seconds:1,prompt_bytes:1,input:1,cached:0,output:1,cost_usd:0,with_usage:1,settings:[]}]};`,context);
assert.equal(context.up(),'','Simulation has no usage panel');
vm.runInContext(`snapshot={mode:'real',usage:[
  {agent:'<b>claude</b>',kind:'implement',attempts:2,outcomes:{done:1,failed:1},seconds:41.6,prompt_bytes:2048,input:43000,cached:33000,output:1200,cost_usd:0.0592,with_usage:2,settings:['haiku/low']},
  {agent:'codex',kind:'review',attempts:1,outcomes:{done:1},seconds:9,prompt_bytes:5000,input:0,cached:0,output:0,cost_usd:0,with_usage:0,settings:['default/default']}]};`,context);
const up = context.up();
assert(!up.includes('<b>claude</b>'),'Agent names are escaped');
assert(up.includes('43.0k (33.0k cached)')&&up.includes('$0.059')&&up.includes('haiku/low')&&up.includes('done:1 failed:1'),'Numbers shown');
assert(/<td>-<\/td><td>-<\/td><td>-<\/td>/.test(up),'An agent that exposed no usage shows dashes, not zeros');
// Integration strip: real mode only, escaped, button enabled only when the runtime says it can promote.
vm.runInContext(`
  project='all';
  snapshot={mode:'simulation',integration:[{project_id:'p',branch:'main',commit:'abcdef0123456789',tasks:[1],checks:[],can_promote:true,busy:null}]};
  globalThis.strip=integrationStrip;
`,context);
assert.equal(context.strip(),'','Simulation must not show the integration strip');
vm.runInContext(`snapshot={mode:'real',integration:[
  {project_id:'<b>p</b>',branch:'<i>main</i>',commit:'abcdef0123456789',tasks:[1,2],checks:[{name:'<u>unit</u>',rc:0},{name:'lint',rc:1}],can_promote:true,busy:null},
  {project_id:'q',branch:'main',commit:'1234567890abcdef',tasks:[3],checks:[],can_promote:false,reason:'your working tree has uncommitted changes',busy:null},
  {project_id:'r',branch:'main',commit:null,tasks:[],checks:[],can_promote:false,busy:'7'}]};`,context);
const strip = context.strip();
assert(!strip.includes('<b>')&&!strip.includes('<i>')&&!strip.includes('<u>'),'Strip must escape project, branch and check names');
assert(strip.includes('abcdef0123')&&strip.includes('lint ✗')&&strip.includes('&lt;u&gt;unit&lt;/u&gt; ✓'),'Commit and per-check results must be shown');
assert(strip.includes('uncommitted changes'),'Reason must be visible when promote is not possible');
assert(strip.includes('checking the merged commit for task 7'));
assert((strip.match(/data-discard=/g)||[]).length===3,'Every integration offers a discard');
assert(!strip.includes('data-review-integration'),'No review button unless the runtime says a review is needed');
vm.runInContext(`snapshot={mode:'real',capabilities:{handoff:{claude_review:false}},integration:[{project_id:'p',branch:'main',commit:'abcdef0123456789',tasks:[1,2],checks:[],can_promote:false,review_needed:true,reason:'needs a review',busy:null}]};`,context);
const needs = context.strip();
const btn = (html, agent) => (html.match(new RegExp('<button[^>]*data-review-integration[^>]*data-agent="'+agent+'"[^>]*>'))||[''])[0];
assert(btn(needs,'claude').includes('disabled')&&btn(needs,'codex').includes('disabled'),'Review needs a logged-in agent');
vm.runInContext(`snapshot.capabilities.handoff={claude_review:true,codex_review:false};`,context);
assert(!btn(context.strip(),'claude').includes('disabled'),'Review with Claude is offered once Claude is logged in');
assert(btn(context.strip(),'codex').includes('disabled'),'Review with Codex stays off until Codex is logged in');
vm.runInContext(`snapshot.capabilities.handoff={claude_review:false,codex_review:true};`,context);
assert(!btn(context.strip(),'codex').includes('disabled')&&btn(context.strip(),'claude').includes('disabled'),'Each agent is gated by its own login');
vm.runInContext(`snapshot={mode:'real',integration:[
  {project_id:'<b>p</b>',branch:'<i>main</i>',commit:'abcdef0123456789',tasks:[1,2],checks:[{name:'<u>unit</u>',rc:0},{name:'lint',rc:1}],can_promote:true,busy:null},
  {project_id:'q',branch:'main',commit:'1234567890abcdef',tasks:[3],checks:[],can_promote:false,reason:'your working tree has uncommitted changes',busy:null},
  {project_id:'r',branch:'main',commit:null,tasks:[],checks:[],can_promote:false,busy:'7'}]};`,context);
const buttons = strip.match(/<button[^>]*data-promote[^>]*>/g);
assert.equal(buttons.length,3);
assert(!buttons[0].includes('disabled'),'Ready integration must be promotable');
assert(buttons[1].includes('disabled')&&buttons[2].includes('disabled'),'Blocked or busy integration must be disabled');
controls().then(()=>console.log('UI checks passed: full patch/result escaping, policy labels, queue escaping, prompt distinction, attention title, confirmation cancellation/stale attempts, displayed source attempt.')).catch(error=>{console.error(error);process.exitCode=1;});
// Brainstorm: everything an agent wrote (questions, plans, objections) is text, never markup; answers go to the asking task.
const evil='<img src=x onerror=alert(1)>';
const card=context.renderers.brainstormCard({id:'7',project_id:'p',goal:evil,phase:'merge',status:'ACTIVE',why:evil,agents:{lead:'claude',other:'codex'},
  qa:[{by:'claude',q:evil,a:evil}],questions:[{task_id:'3',agent:'codex',question:evil,options:[evil],attempt_id:'3-1',pending_id:'3:3-1:WAITING_INPUT'}],
  plan:{summary:evil},objections:evil,created:null});
assert(!card.includes('<img'));
assert(card.includes('&lt;img'));
assert(card.includes('data-q-pending="3:3-1:WAITING_INPUT"'));
assert(card.includes('data-bs-stop="7"'));
assert(!card.includes('data-bs-create'),'Only a finished plan can create tasks');
const ready=context.renderers.brainstormCard({id:'8',project_id:'p',goal:'g',phase:'ready',status:'READY',why:'',agents:{lead:'claude',other:'codex'},qa:[],questions:[],
  plan:{summary:'s'},objections:'',created:null});
assert(ready.includes('data-view="plans"')&&!ready.includes('data-bs-create'),'a finished brainstorm points to the Plans page');
console.log('Brainstorm checks passed.');
// One ask with several questions: each question gets its own choices and box, all text escaped.
const ask=context.renderers.multiAsk([{question:'<b>1</b>',options:['stdin','<img src=x>']},{question:'format?',options:[]}],'data-q-task="9"');
assert(!ask.includes('<b>')&&!ask.includes('<img'));
assert.equal((ask.match(/<textarea/g)||[]).length,2);
assert.equal((ask.match(/data-ask-fill/g)||[]).length,2,'only the first question has choices');
assert(ask.includes('name="a1"'));
const multi=context.renderers.brainstormCard({id:'9',project_id:'p',goal:'g',phase:'clarify',status:'ACTIVE',why:'',agents:{lead:'claude',other:'codex'},qa:[],
  questions:[{task_id:'3',agent:'codex',question:'1) a',options:[],questions:[{question:'a',options:['x']}],attempt_id:'3-1',pending_id:'3:3-1:WAITING_INPUT'}],plan:null,objections:'',created:null});
assert(multi.includes('multi-ask')&&multi.includes('data-q-pending="3:3-1:WAITING_INPUT"'));
console.log('Multi-question checks passed.');
// The two agents' own question tasks stay out of the operator queue while their questions sit in one merged form.
const q2=context.renderers.operatorQueue([{id:'36',title:'t',state:'WAITING_INPUT',held_by:'5',updated_at:1},{id:'40',title:'u',state:'WAITING_INPUT',held_by:null,updated_at:2}]);
assert(!q2.includes('36')&&q2.includes('40')&&q2.includes('1 decision waiting'));
console.log('Held-question checks passed.');
assert(!context.renderers.matchesTaskGroup({state:'WAITING_INPUT',held_by:'5'},'attention'),'a merged-question task is not counted as needing the user');
assert(context.renderers.matchesTaskGroup({state:'WAITING_INPUT',held_by:null},'attention'));
