/* Optional browser integration checks. Install Playwright outside the repository:
 * npm install --prefix /tmp/axon-browser-check playwright
 * NODE_PATH=/tmp/axon-browser-check/node_modules node tests/gui-smoke.cjs
 * npx --prefix /tmp/axon-browser-check playwright install chromium
 */
const { chromium } = require('playwright');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const wait = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'axon-gui-'));
  const server = spawn(process.env.PYTHON || 'python3', ['-m','axon','--sim','--no-browser','--state-dir',folder], {stdio:'ignore'});
  let browser;
  try {
    for (let i=0;i<100&&!fs.existsSync(path.join(folder,'launch.url'));i++) await wait(100);
    const url=fs.readFileSync(path.join(folder,'launch.url'),'utf8').trim();
    const base=url.split('/#')[0], token=new URL(url).hash.split('token=')[1];
    browser=await chromium.launch({headless:true});
    const page=await browser.newPage({viewport:{width:1440,height:1050}});
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    await page.goto(url);
    await page.getByText('Nothing waiting on you').waitFor();
    assert(!page.url().includes('token='),'Token must be removed from address bar');
    await page.reload();
    await page.getByText('Nothing waiting on you').waitFor();
    // Operator commands: keyboard navigation, explicit actions and form protection.
    await page.keyboard.press('Control+k');
    await page.locator('#command-dialog[open]').waitFor();
    await page.getByRole('combobox',{name:'Search commands, tasks and projects'}).fill('your agents');
    await page.keyboard.press('Enter');
    await page.getByRole('heading',{name:'Your agents',exact:true}).waitFor();
    await page.keyboard.press('Alt+1');
    await page.getByRole('heading',{name:'Control room',exact:true}).waitFor();
    await page.getByRole('button',{name:'Open command palette',exact:true}).click();
    await page.locator('#command-search').fill('create new task');
    await page.keyboard.press('Enter');
    await page.locator('#task-dialog[open]').waitFor();
    await page.getByLabel('Title (optional)',{exact:true}).fill('Keep my draft');
    await page.keyboard.press('Alt+2');
    assert(await page.locator('#task-dialog').isVisible(),'Shortcut must not abandon an open form');
    assert.equal(await page.getByLabel('Title (optional)',{exact:true}).inputValue(),'Keep my draft');
    await page.keyboard.press('Escape');
    await page.getByRole('button',{name:'Open command palette',exact:true}).click();
    await page.locator('#command-search').fill('nothing matches this query');
    await page.getByText('No matches. Try a task title, NAV ID or project name.').waitFor();
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    assert(await page.locator('#command-dialog').isVisible(),'Empty search must not run a command');
    await page.keyboard.press('Escape');
    assert(await page.getByRole('button',{name:'Open command palette',exact:true}).evaluate(el=>el===document.activeElement),'Escape must restore opener focus');
    assert.equal(await page.locator('#sync-state').textContent(),'SYNC / LIVE');
    async function create(title,scenario) {
      await page.getByRole('button',{name:'+ New task',exact:true}).click();
      await page.getByLabel('Title (optional)',{exact:true}).fill(title);
      await page.getByLabel('What should the agent do?',{exact:true}).fill('Acceptance criteria for '+title);
      await page.locator('#task-scenario').selectOption(scenario);
      await page.getByRole('button',{name:'Create task →',exact:true}).click();
      await page.locator('#detail-dialog[open]').waitFor();
    }
    await create('Approval lifecycle', 'approval');
    await page.getByRole('button',{name:'Approve simulation',exact:true}).waitFor();
    assert.equal(await page.locator('.operator-request').count(),1,'Pending approval must appear in operator queue');
    await page.getByRole('button',{name:'Approve simulation',exact:true}).click();
    await page.locator('#task-detail .badge.completed').waitFor();
    await page.locator('#detail-dialog').getByRole('button',{name:'Close task details',exact:true}).click();
    await create('Input lifecycle', 'input');
    await page.getByLabel('Your answer',{exact:true}).fill('Test the control contract');
    await page.getByRole('button',{name:'Send answer →',exact:true}).click();
    await page.locator('#task-detail .badge.completed').waitFor();
    await page.locator('#detail-dialog').getByRole('button',{name:'Close task details',exact:true}).click();
    await create('Interrupt lifecycle','hang');
    await page.getByRole('button',{name:'Kill simulation',exact:true}).waitFor();
    await page.getByRole('button',{name:'■ Stop gracefully',exact:true}).click();
    await page.locator('#confirm-dialog').getByRole('button',{name:'Keep task',exact:true}).click();
    assert.equal(await page.locator('#task-detail .badge.running').count(),1,'Cancelled confirmation must keep the task running');
    await page.getByRole('button',{name:'■ Stop gracefully',exact:true}).click();
    await page.locator('#confirm-dialog').getByRole('button',{name:'Confirm stop',exact:true}).click();
    await page.locator('#task-detail .badge.cancelled').waitFor();
    await page.getByRole('button',{name:'↻ Retry as new attempt',exact:true}).click();
    await page.getByRole('button',{name:'Kill simulation',exact:true}).waitFor();
    await page.getByRole('button',{name:'Kill simulation',exact:true}).click();
    await page.locator('#confirm-dialog').getByRole('button',{name:'Confirm kill',exact:true}).click();
    await page.locator('#task-detail .badge.cancelled').waitFor();
    await page.locator('#detail-dialog').getByRole('button',{name:'Close task details',exact:true}).click();
    await page.getByRole('button',{name:'Show completed tasks',exact:true}).click();
    assert.equal(await page.locator('#group-filter').inputValue(),'completed');
    assert.equal(await page.locator('.task-card').count(),2);
    assert.equal(await page.locator('.task-card .badge.completed').count(),2);
    await page.getByRole('textbox',{name:'Search tasks',exact:true}).fill('Approval');
    assert.equal(await page.locator('.task-card').count(),1);
    await page.getByRole('textbox',{name:'Search tasks',exact:true}).fill('<script>');
    assert.equal(await page.locator('.task-card').count(),0);
    await page.locator('.sidebar').getByRole('button',{name:/^Tasks/}).click();
    await page.getByRole('button',{name:'Ⅱ Pause dispatch',exact:true}).click();
    await page.getByRole('button',{name:'▷ Resume dispatch',exact:true}).waitFor();
    await page.getByRole('button',{name:'Add project',exact:true}).click();
    await page.getByLabel('Project name',{exact:true}).fill('PROJECT_AXON');
    await page.locator('#project-dialog').getByRole('button',{name:'Add project',exact:true}).click();
    await page.locator('#project-dialog').waitFor({state:'hidden'});
    await page.getByRole('button',{name:'All projects',exact:true}).click();
    const send = async body => {const r=await fetch(base+'/api/command',{method:'POST',headers:{Authorization:'Bearer '+token,Origin:base,'Content-Type':'application/json'},body:JSON.stringify(body)});assert(r.ok);return r.json();};
    const snap=await (await fetch(base+'/api/snapshot',{headers:{Authorization:'Bearer '+token}})).json();
    await send({action:'create_task',project_id:'project-vela',title:'<img src=x onerror=alert(1)>',spec:'Untrusted title rendering',scope:'docs/',scenario:'success'});
    await page.getByRole('button',{name:'Refresh',exact:true}).click();
    await page.getByRole('heading',{name:'<img src=x onerror=alert(1)>',exact:true}).waitFor();
    assert.equal(await page.locator('.task-card img').count(),0);
    await page.keyboard.press('Control+k');
    await page.locator('#command-search').fill('<img');
    assert.equal(await page.locator('.command-option').count(),1);
    assert.equal(await page.locator('.command-option img').count(),0,'Palette task titles must be escaped');
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    await page.locator('#detail-dialog[open]').waitFor();
    assert.equal(await page.locator('#detail-dialog img').count(),0);
    await page.locator('#detail-dialog').getByRole('button',{name:'Close task details',exact:true}).click();

    // Fresh screenshot with clearly simulated, descriptive work.
    await send({action:'create_task',project_id:'project-vela',title:'Review context broker boundaries',spec:'Confirm local-only context routing in the simulation.',scope:'src/context/',scenario:'approval'});
    await send({action:'create_task',project_id:snap.projects.find(p=>p.name==='PROJECT_AXON').id,title:'Design the agent control contract',spec:'Exercise lifecycle controls using fake-agent.',scope:'axon/',scenario:'success'});
    await send({action:'resume'});
    await wait(6500);
    await send({action:'pause'});
    await page.getByRole('button',{name:'Refresh',exact:true}).click();
    await wait(500);
    if(process.env.AXON_SCREENSHOT){fs.mkdirSync(path.dirname(process.env.AXON_SCREENSHOT),{recursive:true});await page.screenshot({path:process.env.AXON_SCREENSHOT,fullPage:true});}
    await page.setViewportSize({width:390,height:844});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Mobile horizontal overflow');
    await page.getByRole('button',{name:'+ New task',exact:true}).click();
    await page.getByLabel('Title (optional)',{exact:true}).fill('Mobile task');
    await page.getByLabel('What should the agent do?',{exact:true}).fill('Confirm mobile form');
    await page.getByRole('button',{name:'Create task →',exact:true}).click();
    await page.locator('#detail-dialog[open]').waitFor();
    assert.equal(errors.length,0,errors.join('\n'));
    server.kill('SIGINT');
    await page.locator('#detail-dialog').getByRole('button',{name:'Close task details',exact:true}).click();
    await page.getByRole('alert').filter({hasText:'Connection unavailable'}).waitFor();
    assert(await page.getByRole('button',{name:'+ New task',exact:true}).isDisabled());
    assert.equal(await page.locator('#sync-state').textContent(),'SYNC / OFFLINE');
    await page.keyboard.press('Control+k');
    await page.locator('#command-search').fill('create new task');
    assert(await page.getByRole('option').isDisabled(),'Offline palette must disable new tasks');
    await page.keyboard.press('Enter');
    assert(await page.locator('#command-dialog').isVisible(),'Offline action must not execute');

    console.log('Browser checks passed: command keyboard/search/navigation, draft protection, operator queue, statistic filters, palette escaping/offline, approval, input, stop, retry, kill, projects, mobile and disconnect.');
  } finally {
    if(browser) await browser.close();
    server.kill('SIGINT');
    await new Promise(resolve=>{if(server.exitCode!==null)return resolve();server.once('exit',resolve);setTimeout(()=>{server.kill('SIGKILL');resolve();},2000).unref();});
    fs.rmSync(folder,{recursive:true,force:true});
  }
})().catch(e=>{console.error(e);process.exit(1);});
