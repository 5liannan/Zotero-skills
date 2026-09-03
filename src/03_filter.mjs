import { loadConfig, ensureOut, out, readJson, writeJson, log, normDoi, normTitle, reAny, die } from './lib.mjs';

const topic = process.argv[2];
if (!topic) die('用法: node 03_filter.mjs <topic>');
const cfg = loadConfig(topic);
const F = cfg.filter;
if (!F) die('config.filter 缺失');
ensureOut(topic);

const baseline = readJson(out(topic, 'baseline.json'), []) || [];
const baseDOIs = new Set(baseline.map(x => normDoi(x.DOI)).filter(Boolean));
const cands = readJson(out(topic, 'candidates_all.json'), []) || [];
log(`[3/7] 筛选：候选 ${cands.length} 条，其中已在库里 ${cands.filter(c => baseDOIs.has(normDoi(c.doi))).length} 条（将被排除）`);

// 规则模型（与 rbs_task/filter.js 逻辑一致）：
//   命中主桶 = requireAny 有匹配 AND requireContextAny 有匹配
//   命中后若 excludeAny 匹配但 rescueAny 不匹配 -> 丢弃
//   secondary 是第二梯队，规则同上，互相独立去重
function bucketRules(b) {
  return { must: reAny(b.requireAny), ctx: reAny(b.requireContextAny), excl: reAny(b.excludeAny), rescue: reAny(b.rescueAny) };
}
const buckets = [{ name: 'main', rules: bucketRules(F), list: [], seen: new Set(), file: 'filtered_main.json' }];
if (F.secondary) buckets.push({ name: 'secondary', rules: bucketRules(F.secondary), list: [], seen: new Set(), file: 'filtered_secondary.json' });

const stats = { candidates: cands.length, inLibrary: 0, excluded: 0, dupTitle: 0 };
buckets.forEach(b => { stats[b.name] = 0; });

for (const c of cands) {
  if (baseDOIs.has(normDoi(c.doi))) { stats.inLibrary++; continue; }
  const t = c.title;
  for (const b of buckets) {
    const { must, ctx, excl, rescue } = b.rules;
    if (!must || !ctx || !must.test(t) || !ctx.test(t)) continue;
    if (excl && excl.test(t) && !(rescue && rescue.test(t))) { stats.excluded++; break; }
    const n = normTitle(t);
    if (n) { if (b.seen.has(n)) { stats.dupTitle++; break; } b.seen.add(n); }
    b.list.push(c);
    break;
  }
}

for (const b of buckets) {
  b.list.sort((a, b2) => (b2.year || 0) - (a.year || 0));
  writeJson(out(topic, b.file), b.list);
  stats[b.name] = b.list.length;
}
writeJson(out(topic, 'filter_report.json'), stats);
log(`结果：主入围 ${stats.main} 条 / 次级 ${stats.secondary} 条 | 已在库排除 ${stats.inLibrary} | 规则排除 ${stats.excluded} | 标题重复 ${stats.dupTitle}`);

for (const b of buckets) {
  log(`\n--- ${b.name} 入围清单（按年份倒序）---`);
  b.list.forEach(c => log(`${c.year} | ${c.title.slice(0, 96)} | ${c.journal.slice(0, 34)} | ${c.doi}`));
}
log(`\n【人工检查点】逐条审阅 outputs/${topic}/filtered_main.json，`);
log(`把最终要导入的 DOI 每行一个写入 outputs/${topic}/approved_dois.txt（# 开头是注释），然后跑 04_finalize.mjs`);
