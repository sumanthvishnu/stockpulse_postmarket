import test from 'node:test';import assert from 'node:assert/strict';import {targetSession} from './website_schedule.mjs';
test('scheduled night and following morning target intended evening',()=>{
 assert.equal(targetSession(new Date('2026-09-28T15:00:00Z')),'2026-09-28');
 assert.equal(targetSession(new Date('2026-09-28T23:00:00Z')),'2026-09-28');
 assert.equal(targetSession(new Date('2026-10-01T01:00:00Z')),'2026-09-30');
 assert.equal(targetSession(new Date('2026-09-27T15:00:00Z')),'2026-09-27');
});
test('manual date and manual morning invocation are explicit',()=>{
 assert.equal(targetSession(new Date('2026-09-28T23:00:00Z'),'workflow_dispatch'),'2026-09-29');
 assert.equal(targetSession(new Date(),'workflow_dispatch','2026-09-25'),'2026-09-25');
 assert.throws(()=>targetSession(new Date(),'workflow_dispatch','2026-02-31'));
});
