import fs from 'node:fs';
import { loadConfig, ensureOut, out, readJson, log, normDoi, die } from './lib.mjs';

const topic = process.argv[2];
if (!topic) die('用法: node 05_export_ris.mjs <topic>');
const cfg = loadConfig(topic);
const E = cfg.export || {};
ensureOut(topic);

const items = readJson(out(topic, 'final_items.json'), []) || [];
if (!items.length) die('先跑 04_finalize.mjs 生成 final_items.json');
const rm = new Set((cfg.finalize?.excludeDois || []).map(normDoi));
const sel = items.filter(x => !rm.has(normDoi(x.doi)));

const clean = s => (s || '').replace(/&amp;/g, '&').replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/\s+/g, ' ').trim();
function entry(x) {
  let TY = 'JOUR';
  if (x.type === 'proceedings-article') TY = 'CONF';
  else if (x.type === 'book-chapter') TY = 'CHAP';
  else if (x.type === 'posted-content') TY = 'GEN';
  const L = ['TY  - ' + TY];
  for (const a of x.authors || []) { if (a.family || a.given) L.push('AU  - ' + (a.family || '') + ', ' + (a.given || '')); }
  L.push('TI  - ' + clean(x.title));
  if (x.journal) L.push((TY === 'CHAP' ? 'T2  - ' : 'JO  - ') + clean(x.journal));
  if (x.shortjournal && TY === 'JOUR') L.push('JA  - ' + clean(x.shortjournal));
  if (x.year) L.push('PY  - ' + x.year + (x.month ? '/' + String(x.month).padStart(2, '0') : ''));
  if (x.volume) L.push('VL  - ' + x.volume);
  if (x.issue) L.push('IS  - ' + x.issue);
  if (x.page) L.push('SP  - ' + x.page);
  if (x.publisher) L.push('PB  - ' + clean(x.publisher));
  L.push('DO  - ' + x.doi);
  L.push('UR  - https://doi.org/' + x.doi);
  if (x.abstract) L.push('AB  - ' + clean(x.abstract).slice(0, 1500));
  L.push('ER  - ');
  return L.join('\n');
}

let ris = sel.map(entry).join('\n\n');
for (const f of E.extraRis || []) {          // 手工补录条目（如经典老文献 Crossref 收录不全）
  const p = out(topic, f);
  if (fs.existsSync(p)) { ris += '\n\n' + fs.readFileSync(p, 'utf8').replace(/^\uFEFF/, '').replace(/[\r\n]+$/, ''); log('附加手工条目:', f); }
  else log('警告: 手工条目文件不存在，跳过 ->', p);
}
const file = out(topic, E.risFile || 'literature.ris');
fs.writeFileSync(file, '\uFEFF' + ris + '\n', 'utf8');
log(`[5/7] 导出 RIS：${sel.length} 条（排除 ${rm.size} 个 DOI）+ 手工条目 -> ${file}`);
log('该文件可直接拖进 Zotero 导入；若要直接走 API 入库，跑 06_import.mjs ' + topic);
