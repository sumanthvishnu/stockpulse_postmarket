import {readFile, readdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
const root='website-output', repo=process.env.GITHUB_REPOSITORY, token=process.env.GITHUB_TOKEN;
async function api(path,method='GET',body){
 const r=await fetch('https://api.github.com/repos/'+repo+path,{method,headers:{Authorization:'Bearer '+token,Accept:'application/vnd.github+json','Content-Type':'application/json','X-GitHub-Api-Version':'2022-11-28'},body:body?JSON.stringify(body):undefined});
 if(r.status===404&&method==='GET')return null;
 if(!r.ok)throw Error('GitHub publication HTTP '+r.status+' at '+path);
 return r.json();
}
const status=JSON.parse(await readFile(root+'/status.json','utf8'));
const ref=await api('/git/ref/heads/website-reports');
let old={schemaVersion:1,reports:[],latest:null};
if(ref){
 const content=await api('/contents/manifest.json?ref='+ref.object.sha);
 if(content)old=JSON.parse(Buffer.from(content.content,'base64').toString('utf8'));
}
const entries=[...old.reports];
const changes=[];
if(status.state==='available'){
 const entry=status.report;
 if(!/^reports\/\d{4}-\d{2}-\d{2}-[a-f0-9]{16}\.json$/.test(entry.path))throw Error('Invalid report path');
 const payload=await readFile(root+'/'+entry.path,'utf8');
 if(createHash('sha256').update(payload).digest('hex')!==entry.sha256)throw Error('Digest mismatch');
 const existing=entries.find(x=>x.id===entry.id);
 if(existing&&existing.sha256!==entry.sha256)throw Error('Immutable report mismatch');
 if(!existing)entries.push(entry);
 changes.push({path:entry.path,mode:'100644',type:'blob',content:payload});
}
entries.sort((a,b)=>b.session.localeCompare(a.session)||b.generatedAt.localeCompare(a.generatedAt));
const manifest={schemaVersion:1,updatedAt:new Date().toISOString(),schedule:'20:30 Asia/Kolkata',latest:entries[0]?.id||null,reports:entries,latestAttempt:status};
changes.push({path:'manifest.json',mode:'100644',type:'blob',content:JSON.stringify(manifest)});
const parent=ref?await api('/git/commits/'+ref.object.sha):null;
const tree=await api('/git/trees','POST',{...(parent?{base_tree:parent.tree.sha}:{}),tree:changes});
const commit=await api('/git/commits','POST',{message:'Post-market website '+status.session+' ('+status.state+')',tree:tree.sha,parents:ref?[ref.object.sha]:[]});
if(ref)await api('/git/refs/heads/website-reports','PATCH',{sha:commit.sha,force:false});
else await api('/git/refs','POST',{ref:'refs/heads/website-reports',sha:commit.sha});
console.log(JSON.stringify({state:status.state,report:status.report?.id||null,publicationCommit:commit.sha,modelCalls:0}));
