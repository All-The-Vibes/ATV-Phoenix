/**
 * verify-ui.mjs -- behavioral UI acceptance gate template (issue #15)
 *
 * Proves UI features WORK, not just that they exist in the DOM.
 * Catches three failure classes simpler gates miss:
 *   1. Invisible content: element present but renders as zero-height strip.
 *      Gate: bounding box height/width >= minimum.
 *   2. Toggle does nothing: class changes but page never repaints.
 *      Gate: background luminance delta >= 0.3 before/after interaction.
 *   3. State lost on reload. Gate: reload + assert class survives.
 *
 * Based on the proven pattern from the dogfood run (issue #15 reference impl).
 * Complements verify-live.mjs (HTTP 200 + DOM content); this proves BEHAVIOR.
 *
 * phoenix_sense gate:
 *   { `kind`: `command_exit`, `target`: [`node`, `scripts/verify-ui.mjs`], `expect`: 0, `cwd`: `.` }
 *
 * Usage: node verify-ui.mjs [--json] [--skip-server]
 * Requires: playwright (npm i -D playwright), running server (or --skip-server).
 */

import { chromium } from 'playwright';
import { spawn } from 'child_process';
import { setTimeout as sleep } from 'timers/promises';
import { mkdirSync } from 'fs';
// ---- CONFIGURE FOR YOUR PROJECT -------------------------------------------
const PORT         = parseInt(process.env.PORT ?? '3000', 10);
const START_CMD    = process.env.START_CMD ?? 'npm';
const START_ARGS   = (process.env.START_ARGS ?? 'start').split(' ');
const READY_MS     = 30_000;

// CHECKS: array of { url, steps[] }. Define your behavioral assertions here.
// Copy the commented example, adjust selectors, and remove the comment markers.
const CHECKS = [
  // { url: '/', steps: [
  //   { assert_bbox:            { selector: '[data-hero]', min_height: 340 } },
  //   { assert_luminance:       { selector: 'body', min: 0.6 } },
  //   { screenshot:             { filename: 'screenshots/light.png' } },
  //   { click_role:             { role: 'button', name: '/theme|dark|light|mode/' } },
  //   { assert_class:           { selector: 'html', contains: 'dark' } },
  //   { assert_luminance:       { selector: 'body', max: 0.4 } },
  //   { assert_luminance_delta: { selector: 'body', min_delta: 0.3 } },
  //   { screenshot:             { filename: 'screenshots/dark.png' } },
  //   { reload:                 {} },
  //   { assert_class:           { selector: 'html', contains: 'dark' } },
  // ]},
];
// ---- END CONFIGURATION -----------------------------------------------------

const JSON_MODE   = process.argv.includes('--json');
const SKIP_SERVER = process.argv.includes('--skip-server');
const results     = { ok: true, checks: [], errors: [] };
const prevLum     = {};

function log(m) { if (!JSON_MODE) console.log(m); }
function fail(m) { results.ok = false; results.errors.push(m); log('  FAIL: ' + m); }

function rl(r, g, b) {
  return [r,g,b].map(c => { const s=c/255; return s<=0.03928?s/12.92:Math.pow((s+0.055)/1.055,2.4); })
    .reduce((a,v,i) => a+[0.2126,0.7152,0.0722][i]*v, 0);
}
async function lum(page, sel) {
  const rgb = await page.evaluate(s => {
    const e=document.querySelector(s); if(!e) return null;
    const m=window.getComputedStyle(e).backgroundColor.match(/\d+/g);
    return m?[+m[0],+m[1],+m[2]]:null;
  }, sel);
  return rgb ? rl(...rgb) : null;
}

let srv=null;
function startSrv(){ srv=spawn(START_CMD,START_ARGS,{stdio:'ignore',detached:false,shell:process.platform==='win32'}); }
function stopSrv(){ if(!srv)return; try{ process.platform==='win32'?spawn('taskkill',['/pid',String(srv.pid),'/T','/F'],{stdio:'ignore',shell:true}):process.kill(-srv.pid,'SIGTERM'); }catch(_){} srv=null; }
async function waitSrv(){ const dl=Date.now()+READY_MS; while(Date.now()<dl){ try{const r=await fetch('http://localhost:'+PORT+'/',{signal:AbortSignal.timeout(1000)});if(r.ok||r.status<500)return true;}catch(_){} await sleep(500); } return false; }

async function runStep(page,step,label){
  if(step.assert_bbox){
    const{selector:s,min_width:mw=0,min_height:mh=0}=step.assert_bbox;
    const bb=await page.locator(s).first().boundingBox().catch(()=>null);
    if(!bb)return fail(label+': assert_bbox "'+s+'" not visible');
    if(bb.width<mw)fail(label+': assert_bbox "'+s+'" width '+bb.width+' < '+mw);
    if(bb.height<mh)fail(label+': assert_bbox "'+s+'" height '+bb.height+' < '+mh);
  }else if(step.assert_luminance){
    const{selector:s,min,max}=step.assert_luminance;
    const v=await lum(page,s);
    if(v===null)return fail(label+': assert_luminance "'+s+'" not found');
    if(min!==undefined&&v<min)fail(label+': lum='+v.toFixed(3)+' < min='+min);
    if(max!==undefined&&v>max)fail(label+': lum='+v.toFixed(3)+' > max='+max);
    prevLum[s]=v;
  }else if(step.assert_luminance_delta){
    const{selector:s,min_delta}=step.assert_luminance_delta;
    const v=await lum(page,s),p=prevLum[s];
    if(v===null||p===undefined)return fail(label+': assert_luminance_delta no prior lum for "'+s+'"');
    if(Math.abs(v-p)<min_delta)fail(label+': delta='+Math.abs(v-p).toFixed(3)+' < '+min_delta+' (may not repaint)');
    prevLum[s]=v;
  }else if(step.click_role){
    const{role,name}=step.click_role;
    const re=typeof name==='string'&&name.startsWith('/')?new RegExp(name.slice(1,name.lastIndexOf('/')),name.slice(name.lastIndexOf('/')+1)):name;
    const btn=page.getByRole(role,{name:re}).first();
    if(!await btn.count())return fail(label+': click_role role="'+role+'" name="'+name+'" not found');
    await btn.click();await page.waitForTimeout(300);
  }else if(step.assert_class){
    const{selector:s,contains:c}=step.assert_class;
    const has=await page.evaluate(([sel,cls])=>document.querySelector(sel)?.classList.contains(cls)??false,[s,c]);
    if(!has)fail(label+': assert_class "'+s+'" missing class "'+c+'"');
  }else if(step.assert_no_class){
    const{selector:s,contains:c}=step.assert_no_class;
    const has=await page.evaluate(([sel,cls])=>document.querySelector(sel)?.classList.contains(cls)??false,[s,c]);
    if(has)fail(label+': assert_no_class "'+s+'" unexpectedly has "'+c+'"');
  }else if(step.reload){
    await page.reload({waitUntil:'load'});
  }else if(step.screenshot){
    const f=step.screenshot.filename??'screenshots/shot.png';
    mkdirSync(f.includes('/')?f.substring(0,f.lastIndexOf('/')):'.',{recursive:true});
    await page.screenshot({path:f,fullPage:true});log('    screenshot: '+f);
  }
}

async function main(){
  if(CHECKS.length===0){
    const msg='No CHECKS configured. Define your assertions in the CHECKS array at the top of this file.';
    log('[verify-ui] '+msg);
    if(JSON_MODE)process.stdout.write(JSON.stringify({ok:true,checks:[],errors:[],note:msg})+'\n');
    process.exit(0);
  }
  if(!SKIP_SERVER){ log('[verify-ui] starting server...'); startSrv(); if(!await waitSrv()){fail('server not ready on :'+PORT);stopSrv();if(JSON_MODE)process.stdout.write(JSON.stringify(results)+'\n');process.exit(1);} log('[verify-ui] ready on :'+PORT); }
  const browser=await chromium.launch();
  try{
    for(const check of CHECKS){
      const label=check.url??'/'; log('  '+label+'...');
      const page=await browser.newContext().then(c=>c.newPage());
      await page.goto((SKIP_SERVER?'':'http://localhost:'+PORT)+(check.url??'/'),{waitUntil:'load',timeout:15000});
      for(const step of(check.steps??[]))await runStep(page,step,label);
      results.checks.push({url:check.url,ok:results.errors.length===0});
      await page.close();
    }
  }finally{await browser.close();stopSrv();}
  if(JSON_MODE)process.stdout.write(JSON.stringify(results)+'\n');
  else{const p=results.checks.filter(c=>c.ok).length;console.log('[verify-ui] '+p+'/'+results.checks.length+' OK  errors='+results.errors.length);results.errors.forEach(e=>console.error('  ERR: '+e));}
  process.exit(results.ok?0:1);
}
process.on('SIGTERM',()=>{stopSrv();process.exit(1);});
process.on('uncaughtException',err=>{console.error(err);stopSrv();process.exit(1);});
main().catch(err=>{console.error(err);stopSrv();process.exit(1);});
