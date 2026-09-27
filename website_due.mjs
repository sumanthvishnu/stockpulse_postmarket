import {appendFile} from 'node:fs/promises';
import {targetSession} from './website_schedule.mjs';
const event=process.env.GITHUB_EVENT_NAME, manual=process.env.MANUAL_DATE, marker=process.env.INITIAL_REPLAY;
let run=true;
const session=targetSession(new Date(),event,manual||marker||'');
if(event==='push'&&!marker)run=false;
if(run&&!manual&&!marker){
 const today=session;
 const response=await fetch('https://api.github.com/repos/'+process.env.GITHUB_REPOSITORY+'/contents/manifest.json?ref=website-reports',{headers:{Authorization:'Bearer '+process.env.GITHUB_TOKEN,Accept:'application/vnd.github+json'}});
 if(response.ok){
  const body=await response.json();const manifest=JSON.parse(Buffer.from(body.content,'base64').toString('utf8'));
  if(manifest.reports?.some(r=>r.session===today)||(manifest.latestAttempt?.session===today&&manifest.latestAttempt?.state==='market_closed'))run=false;
 }else if(response.status!==404)throw Error('Cannot check prior publication: '+response.status);
}
await appendFile(process.env.GITHUB_OUTPUT,'run='+run+'\nsession='+session+'\n');console.log(run?'A new edition may run.':'No duplicate collection is needed.');
