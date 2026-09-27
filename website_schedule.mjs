export function targetSession(now=new Date(),event='schedule',manual=''){
 if(manual){if(!/^\d{4}-\d{2}-\d{2}$/.test(manual)||new Date(manual+'T00:00:00Z').toISOString().slice(0,10)!==manual)throw Error('Invalid session');return manual;}
 const parts=Object.fromEntries(new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',hourCycle:'h23'}).formatToParts(now).map(p=>[p.type,p.value]));
 let day=parts.year+'-'+parts.month+'-'+parts.day;
 // A scheduler invocation delayed into the next morning belongs to last evening.
 if(event==='schedule'&&Number(parts.hour)<12)day=new Date(Date.parse(day+'T00:00:00Z')-86400000).toISOString().slice(0,10);
 return day;
}
