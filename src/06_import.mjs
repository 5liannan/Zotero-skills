import { loadConfig, ensureOut, out, readJson, writeJson, log, normDoi, sleep, zoteroBase, zoteroSaveItem, zoteroSaveItems, zoteroUpdateSession, toZoteroItem, die } from './lib.mjs';

const topic = process.argv[2];
const mode = process.argv[3] === '--batch' ? 'batch' : 'per-item';
if (!topic) die('用法: node 06_import.mjs <topic> [--batch]');
const cfg = loadConfig(topic);
const base = zoteroBase(cfg);
ensureOut(topic);

const items = readJson(out(topic, 'final_items.json'), []) || [];
if (!items.length) die('先跑 04_finalize.mjs 生成 final_items.json');
const rm = new Set((cfg.finalize?.excludeDois || []).map(normDoi));
const sel = items.filter(x => !rm.has(normDoi(x.doi)));
const target = cfg.zotero?.collectionKey, tags = cfg.zotero?.tags || [];
log(`[6/7] 入库 ${sel.length} 条（模式 ${mode}）-> ${base}${target ? '，分类 ' + target : '（未配置分类，仅入库）'}`);

if (mode === 'batch') {
  const sid = `litwf-${topic}-batch`;
  const payload = sel.map(x => toZoteroItem(x, topic));
  const r = await zoteroSaveItems(base, sid, payload);
  log('saveItems:', r.status, r.body);
  if (r.status === 201) { await sleep(3000); await tagSessions(base, [sid], target, tags); }
  writeJson(out(topic, 'import_results.json'), { mode, items: payload.map(p => ({ doi: p.DOI, status: r.status })) });
  process.exit(r.status === 201 ? 0 : 1);
}

// per-item 模式：一条一个 session。失败只影响那一条，也方便事后逐条归档/打标签。
const prev = readJson(out(topic, 'import_results.json'), null);
const done = new Set((prev?.items || []).filter(r => r.status === 201).map(r => normDoi(r.doi)));
const results = (prev?.items || []).filter(r => r.status === 201);
let ok = results.length, fail = 0, i = 0;

for (const x of sel) {
  i++;
  if (done.has(normDoi(x.doi))) continue;            // 断点续跑：已成功的跳过
  const it = toZoteroItem(x, topic);
  const sid = `litwf-${topic}-${i}`;
  const r = await zoteroSaveItem(base, sid, it);
  if (r.status === 201) { ok++; results.push({ doi: x.doi, sessionID: sid, status: 201 }); }
  else { fail++; results.push({ doi: x.doi, sessionID: sid, status: r.status, body: r.body }); log(`  FAIL ${i} ${x.doi} ${r.status} ${r.body.slice(0, 100)}`); }
  writeJson(out(topic, 'import_results.json'), { mode, items: results });
  await sleep(150);
}
writeJson(out(topic, 'import_results.json'), { mode, items: results });
log(`入库完成：成功 ${ok} / 失败 ${fail}（失败明细见 import_results.json，修好原因后重跑本脚本即可只补失败条目）`);

if (target) {
  const sids = results.filter(r => r.status === 201).map(r => r.sessionID);
  await tagSessions(base, sids, target, tags);
}
async function tagSessions(base, sids, target, tags) {
  if (!sids.length) return;
  let n = 0;
  for (const sid of sids) {
    const r = await zoteroUpdateSession(base, sid, target, tags);
    if (r.status === 200) n++; else log('  updateSession 失败', sid, r.status);
    await sleep(80);
  }
  log(`已归档 ${n}/${sids.length} 个 session${target ? ' -> 分类 ' + target : ''}${tags.length ? '，标签 ' + tags.join(' / ') : ''}`);
}
log('下一步：node 07_attach_pdfs.mjs ' + topic);
