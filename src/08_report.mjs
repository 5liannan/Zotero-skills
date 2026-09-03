import { loadConfig, ensureOut, out, readJson, writeText, log, normDoi, stamp, toBibtex, die } from './lib.mjs';

// 阶段 8：汇总报告。读 final_items.json（04 的产物）+ 可选的人工注记 curated.json，
// 按注记关键词分类，生成 report.md 与 references.bib。不联网、可重复跑。
//
// curated.json 格式（人工/Agent 逐条写）：
//   [ { "doi": "10.1364/OL.15.001038", "note": "BOTDA 首创实验，奠基性经典" }, ... ]
// 分类规则在 config.report.categories：按顺序匹配 note 中的关键词，第一个命中的类生效；
// 都不中落 defaultCategory。不配 report 时全部进「文献清单」。
const topic = process.argv[2];
if (!topic) die('用法: node 08_report.mjs <topic>');
const cfg = loadConfig(topic);
ensureOut(topic);

const finals = readJson(out(topic, 'final_items.json'), []) || [];
if (!finals.length) die('先跑 04_finalize.mjs 生成 final_items.json');
const rm = new Set((cfg.finalize?.excludeDois || []).map(normDoi));
const sel = finals.filter(x => !rm.has(normDoi(x.doi)));

const curated = new Map((readJson(out(topic, 'curated.json'), []) || [])
  .map(c => [normDoi(c.doi), (c.note || '').trim()]).filter(([d, n]) => d && n));

// 挂载情况（07 跑过才有）
const pdfs = new Map((readJson(out(topic, 'pdf_results.json'), []) || [])
  .filter(r => r.status === 'attached').map(r => [normDoi(r.doi), r.len || 0]));

const R = cfg.report || {};
const categories = R.categories || [];
const defCat = R.defaultCategory || '文献清单';
const catOf = x => {
  const note = curated.get(normDoi(x.doi)) || '';
  for (const c of categories) if ((c.noteAny || []).some(k => note.includes(k))) return c.name;
  return defCat;
};

const groups = new Map();
for (const x of sel) {
  const g = catOf(x);
  if (!groups.has(g)) groups.set(g, []);
  groups.get(g).push(x);
}
const order = [...categories.map(c => c.name), defCat].filter((n, i, a) => a.indexOf(n) === i);

const L = [];
L.push(`# ${R.title || (cfg.title || topic) + ' 文献报告'}\n`);
if (R.intro) L.push(R.intro + '\n');
L.push(`生成时间：${stamp()}　|　定稿 ${sel.length} 篇　|　已挂全文 PDF ${pdfs.size} 篇　|　人工注记 ${curated.size} 条\n`);

L.push('## 结果概览\n');
for (const g of order) if (groups.get(g)) L.push(`- **${g}**：${groups.get(g).length} 篇`);
L.push('');

for (const g of order) {
  const rs = (groups.get(g) || []).slice().sort((a, b) => (a.year || 0) - (b.year || 0));
  if (!rs.length) continue;
  L.push(`## ${g}（${rs.length} 篇）\n`);
  for (const r of rs) {
    const d = normDoi(r.doi);
    const aus = (r.authors || []).map(a => a.family).filter(Boolean);
    const au = aus.slice(0, 3).join(', ') + (aus.length > 3 ? ' 等' : '');
    const pdf = pdfs.has(d) ? '　✔ 全文PDF' : '';
    const note = curated.get(d) ? `　｜ ${curated.get(d)}` : '';
    L.push(`- **${r.title}** (${r.year || 'n.d.'}). ${au}. *${r.journal || ''}*${r.volume ? ', ' + r.volume : ''}${r.issue ? '(' + r.issue + ')' : ''}${r.page ? ', ' + r.page : ''}. DOI: [${r.doi}](https://doi.org/${r.doi})${pdf}${note}`);
  }
  L.push('');
}

// 过程统计（03 跑过才有）
const fr = readJson(out(topic, 'filter_report.json'), null);
if (fr) {
  L.push('## 过程统计\n');
  L.push(`候选 ${fr.candidates ?? '-'} 条 → 已在库排除 ${fr.inLibrary ?? '-'}、标题相似排除 ${fr.inLibrarySim ?? '-'}、规则排除 ${fr.excluded ?? '-'}、标题重复 ${fr.dupTitle ?? '-'} → 主入围 ${fr.main ?? '-'} / 次入围 ${fr.secondary ?? 0}\n`);
}

if (R.notes?.length) {
  L.push('## 说明与建议\n');
  R.notes.forEach((n, i) => L.push(`${i + 1}. ${n}`));
  L.push('');
}

writeText(out(topic, R.reportFile || 'report.md'), L.join('\n') + '\n');
writeText(out(topic, R.bibFile || 'references.bib'), sel.map(toBibtex).join('\n\n') + '\n');
log(`[8] 报告 ${sel.length} 条（分类 ${order.filter(g => groups.get(g)).length} 类）-> ${R.reportFile || 'report.md'} | BibTeX -> ${R.bibFile || 'references.bib'}`);
log(`分类分布：${order.filter(g => groups.get(g)).map(g => `${g} ${groups.get(g).length}`).join(' / ')}`);
