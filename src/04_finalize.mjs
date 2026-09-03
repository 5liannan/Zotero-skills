import fs from 'node:fs';
import { loadConfig, ensureOut, out, readJson, writeJson, log, normDoi, sleep, fetchJson, CROSSREF_SELECT, die } from './lib.mjs';

const topic = process.argv[2];
if (!topic) die('用法: node 04_finalize.mjs <topic>');
const cfg = loadConfig(topic);
ensureOut(topic);

// DOI 来源优先级：人工审定的 approved_dois.txt > config.finalize.dois
const listFile = out(topic, 'approved_dois.txt');
let dois;
if (fs.existsSync(listFile)) {
  dois = fs.readFileSync(listFile, 'utf8').split(/\r?\n/).map(s => s.trim()).filter(s => s && !s.startsWith('#')).map(normDoi);
  log(`读取人工审定清单 ${listFile}：${dois.length} 个 DOI`);
} else if (cfg.finalize?.dois?.length) {
  dois = cfg.finalize.dois.map(normDoi);
  log(`使用 config.finalize.dois：${dois.length} 个 DOI（建议改用 approved_dois.txt，便于版本管理）`);
} else die(`缺少审定清单：先创建 outputs/${topic}/approved_dois.txt（每行一个 DOI）`);

dois = [...new Set(dois)];
const baseline = readJson(out(topic, 'baseline.json'), []) || [];
const baseDOIs = new Set(baseline.map(x => normDoi(x.DOI)).filter(Boolean));
const cands = new Map((readJson(out(topic, 'candidates_all.json'), []) || []).map(c => [normDoi(c.doi), c]));
const headers = { 'User-Agent': `lit-workflow/1.0 (mailto:${cfg.search?.mailto || 'user@example.com'})` };

const finals = [], fails = [];
for (const doi of dois) {
  if (baseDOIs.has(doi)) { log('  跳过（已在库）:', doi); continue; }
  let m = null;
  try {
    const r = await fetchJson(`https://api.crossref.org/works/${encodeURIComponent(doi)}?select=${encodeURIComponent(CROSSREF_SELECT)}`, { headers });
    m = r.message;
  } catch { /* 落到候选池兜底 */ }
  if (!m) { if (cands.has(doi)) m = cands.get(doi); else { fails.push(doi); log('  拉取失败:', doi); continue; } }
  finals.push({
    doi, title: ((m.title && m.title[0]) || '').replace(/<[^>]+>/g, '').trim(),
    journal: ((m['container-title'] && m['container-title'][0]) || '').trim(),
    shortjournal: (m['short-container-title'] && m['short-container-title'][0]) || '',
    year: (m.issued?.['date-parts']?.[0]?.[0]) || '',
    month: (m.issued?.['date-parts']?.[0]?.[1]) || '',
    volume: m.volume || '', issue: m.issue || '', page: m.page || '',
    type: m.type || '', publisher: m.publisher || '',
    abstract: ((m.abstract || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()),
    authors: (m.author || []).map(a => ({ family: a.family || '', given: a.given || '' }))
  });
  await sleep(150);
}

finals.sort((a, b) => (a.year || 0) - (b.year || 0));
writeJson(out(topic, 'final_items.json'), finals);
writeJson(out(topic, 'finalize_errors.json'), fails);
log(`[4/7] 定稿 ${finals.length} 条 -> final_items.json | 失败 ${fails.length} 条 -> finalize_errors.json`);

log('--- 快速核对 ---');
finals.forEach(r => log(`${r.year} | ${(r.type || '').slice(0, 10).padEnd(10)} | ${r.title.replace(/\s+/g, ' ').slice(0, 82)} | ${r.journal.slice(0, 28)}`));
log('\n下一步：node 05_export_ris.mjs ' + topic);
