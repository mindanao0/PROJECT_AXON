/* Optional browser check of the real runtime (fake-agent, sandboxed, no quota): create a task, add it to
 * the integration branch, fast-forward the user's branch. Needs bubblewrap and a systemd user session.
 * NODE_PATH=/tmp/axon-browser-check/node_modules node tests/gui-real-smoke.cjs   (see gui-smoke.cjs) */
const { chromium } = require('playwright');
const { spawn, execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');
const wait = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const root = fs.mkdtempSync(path.join('/tmp', 'nvg-')), proj = path.join(root, 'proj'), state = path.join(root, 'state');
  const git = (...a) => execFileSync('git', ['-C', proj, '-c', 'user.name=t', '-c', 'user.email=t@t', ...a], {encoding: 'utf8'});
  fs.mkdirSync(path.join(proj, 'src'), {recursive: true}); fs.mkdirSync(path.join(root, 'cfg/projects'), {recursive: true});
  fs.writeFileSync(path.join(proj, 'src/a.py'), 'a = 1\n');
  git('init', '-q', '-b', 'main'); git('add', '-A'); git('commit', '-qm', 'init');
  fs.writeFileSync(path.join(root, 'cfg/projects/demo.toml'), `path = "${proj}"\nprotected = []\n[checks]\nok = "true"\n`);
  const server = spawn(process.env.PYTHON || 'python3', ['-m', 'axon', '--port', '0', '--no-browser', '--state-dir', state],
    {stdio: 'ignore', env: {...process.env, AXON_HOME: path.join(root, 'home'), AXON_CONFIG: path.join(root, 'cfg')}});
  let browser;
  try {
    for (let i = 0; i < 100 && !fs.existsSync(path.join(state, 'launch.url')); i++) await wait(100);
    const url = fs.readFileSync(path.join(state, 'launch.url'), 'utf8').trim();
    browser = await chromium.launch({headless: true});
    const page = await browser.newPage({viewport: {width: 1440, height: 1050}});
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.goto(url);
    await page.getByRole('button', {name: '+ New task', exact: true}).click();
    await page.getByLabel('Title (optional)', {exact: true}).fill('Add x');
    await page.getByLabel('What should the agent do?', {exact: true}).fill(
      '[[step]]\ndo = "edit"\npath = "src/x.py"\ntext = "x = 1\\n"\n[[step]]\ndo = "mcp"\ntool = "report_result"\nargs = {status = "done", summary = "ok"}\n');
    await page.locator('#task-agent').selectOption('fake');
    await page.getByRole('button', {name: 'Create task →', exact: true}).click();
    await page.locator('#task-detail .badge.completed').waitFor({timeout: 60000});
    const before = git('rev-parse', 'HEAD').trim();
    await page.getByRole('button', {name: 'Add to integration branch', exact: true}).click();
    await page.locator('#detail-dialog').getByRole('button', {name: 'Close task details', exact: true}).click();
    const strip = page.locator('.integration-strip');
    await strip.getByText('ok ✓').waitFor({timeout: 60000});
    assert.equal(git('rev-parse', 'HEAD').trim(), before, 'Integrating must not touch the user branch');
    // Roll back, then integrate again: the branch is only a proposal until the user fast-forwards.
    await strip.getByRole('button', {name: 'Discard', exact: true}).click();
    await page.locator('#confirm-dialog').getByRole('button', {name: 'Confirm discard', exact: true}).click();
    await page.locator('.integration-strip').waitFor({state: 'detached', timeout: 15000});
    let gone = false; try { git('rev-parse', '--verify', '-q', 'refs/axon/integration/demo'); } catch (_) { gone = true; }
    assert(gone, 'Discard must remove the integration ref');
    await page.locator('[data-task]').first().click();
    await page.getByRole('button', {name: 'Add to integration branch', exact: true}).click();
    await page.locator('#detail-dialog').getByRole('button', {name: 'Close task details', exact: true}).click();
    await page.locator('.integration-strip').getByText('ok ✓').waitFor({timeout: 60000});
    const promote = strip.getByRole('button', {name: /Fast-forward main/});
    await promote.waitFor(); assert(await promote.isEnabled());
    await promote.click();
    await page.locator('#confirm-dialog').getByRole('button', {name: 'Confirm fast-forward', exact: true}).click();
    await page.locator('.integration-strip').waitFor({state: 'detached', timeout: 15000});
    assert.notEqual(git('rev-parse', 'HEAD').trim(), before);
    assert.equal(git('show', 'HEAD:src/x.py'), 'x = 1\n');
    assert.equal(git('status', '--porcelain').trim(), '');
    // A dependent task verified by one check, created from the form; the usage view lists the finished attempts.
    await page.getByRole('button', {name: '+ New task', exact: true}).click();
    await page.getByLabel('Title (optional)', {exact: true}).fill('Add y after x');
    await page.getByLabel('What should the agent do?', {exact: true}).fill(
      '[[step]]\ndo = "edit"\npath = "src/y.py"\ntext = "y = 1\\n"\n[[step]]\ndo = "mcp"\ntool = "report_result"\nargs = {status = "done", summary = "ok"}\n');
    await page.locator('#task-agent').selectOption('fake');
    await page.locator('#task-after').selectOption({index: 1});
    await page.locator('#task-checks-list input[value="ok"]').check();
    await page.getByRole('button', {name: 'Create task →', exact: true}).click();
    await page.locator('#task-detail').getByText('Starts after').waitFor();
    await page.locator('#task-detail').getByText('Verified by').waitFor();
    await page.locator('#task-detail .badge.completed').waitFor({timeout: 60000});
    await page.locator('#detail-dialog').getByRole('button', {name: 'Close task details', exact: true}).click();
    await page.locator('.sidebar [data-view="agents"]').click();
    await page.getByText('Usage, last 24 hours').waitFor();
    assert(await page.locator('.usage-table').innerText().then(x => x.includes('fake') && x.includes('implement')), 'usage table lists the fake attempts');
    // Model and effort: set in Settings, saved to config.toml, offered again after a reload.
    await page.locator('.sidebar [data-view="settings"]').click();
    await page.locator('#agent-options-form [name="claude_model"]').fill('haiku');
    await page.locator('#agent-options-form [name="claude_effort"]').selectOption('low');
    await page.getByRole('button', {name: 'Save model and effort', exact: true}).click();
    await page.locator('#toast', {hasText: 'Model and effort saved'}).waitFor();
    const saved = fs.readFileSync(path.join(root, 'cfg', 'config.toml'), 'utf8');
    assert(/claude_model = "haiku"/.test(saved) && /claude_effort = "low"/.test(saved), 'config.toml must hold the setting: ' + saved);
    await page.reload();
    await page.locator('.sidebar [data-view="settings"]').click();
    assert.equal(await page.locator('#agent-options-form [name="claude_effort"]').inputValue(), 'low');
    await page.locator('#agent-options-form [name="claude_effort"]').selectOption('ultra').catch(() => {});  // not offered for claude
    await page.locator('#agent-options-form [name="codex_effort"]').selectOption('ultra');  // offered for codex
    // the new-task form offers the selected agent's model suggestions and effort levels
    await page.getByRole('button', {name: '+ New task', exact: true}).click();
    await page.locator('#task-agent').selectOption('claude');
    assert.equal(await page.locator('#task-model-row').isVisible(), true);
    assert.equal(await page.locator('#task-model').getAttribute('placeholder'), 'default: haiku');
    assert((await page.locator('#task-effort option').allInnerTexts()).includes('Default (low)'));
    await page.locator('#task-agent').selectOption('fake');
    assert.equal(await page.locator('#task-model-row').isVisible(), false);
    await page.locator('#task-dialog [data-close="task-dialog"]').first().click();
    for (const view of ['tasks', 'plans', 'brainstorm', 'agents', 'activity', 'settings']) {  // every page still renders
      await page.locator(`.sidebar [data-view="${view}"]`).click();
      assert(await page.locator('#content').innerText().then(x => x.trim().length > 20), `view ${view} rendered nothing`);
    }
    assert.equal(errors.length, 0, errors.join('\n'));
    console.log('Real-runtime browser checks passed: create, integrate, discard, integrate again, fast-forward.');
  } finally {
    if (browser) await browser.close();
    server.kill('SIGINT');
    await new Promise(r => { if (server.exitCode !== null) return r(); server.once('exit', r); setTimeout(() => { server.kill('SIGKILL'); r(); }, 3000).unref(); });
    fs.rmSync(root, {recursive: true, force: true});
  }
})().catch(e => { console.error(e); process.exit(1); });
