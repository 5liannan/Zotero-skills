// 一次性迁移工具：从 rbs_task 的旧脚本里机械提取配置，生成 topics/rbs.json 与审定清单。
// 用途：避免手工转录 50 组关键词和 84 个 DOI 时出错。迁移其他旧项目时可照抄此思路。
import fs from 'node:fs';
import { root, writeJson, writeText, log } from '../src/lib.mjs';

const SRC = 'C:/Users/Administrator/Desktop/rbs_task';
const js = f => fs.readFileSync(SRC + '/' + f, 'utf8');

const searchJs = js('search_crossref.js'), round2Js = js('round2.js'), finJs = js('finalize.js'), filterJs = js('filter.js'), bisectJs = js('bisect.js');

// 1. 关键词（含 filter 日期限定）
const q1 = [...searchJs.matchAll(/\{q:'([^']*)'(?:,filter:'([^']*)')?\}/g)].map(m => m[2] ? { q: m[1], filter: m[2] } : { q: m[1] });
const q2 = [...round2Js.matchAll(/\{q:'([^']*)'\}/g)].map(m => ({ q: m[1] }));

// 2. 正则规则（直接从 filter.js 抠出来，避免转录走样）
const rx = name => { const m = filterJs.match(new RegExp('const ' + name + '=/(.*?)/[a-z]*;')); return m ? m[1] : ''; };
const GAS = rx('GAS'), FIB = rx('FIB'), KEEP = rx('KEEP_NONBR');
if (!GAS || !FIB || !KEEP) { console.error('正则提取失败', { GAS, FIB, KEEP }); process.exit(1); }
const BR = 'brillouin';
const STRONG = 'Tenti|Landau.?Placzek|kinetic model';
const GAS_WORDS = 'gas|air|CO2|SF6|nitrogen|argon|hydrogen|methane';

// 3. 84 个审定 DOI + 4 个排除 DOI（rm 数组在 bisect.js / build_ris.js / import.js 里，finalize.js 没有）
const dois = [...finJs.matchAll(/'(10\.[^']*)'/g)].map(m => m[1]);
const rmMatch = bisectJs.match(/const rm=\[([^\]]*)\]/);
const rm = rmMatch ? [...rmMatch[1].matchAll(/'([^']+)'/g)].map(m => m[1]) : [];

// 4. 手工补录条目：原 RIS 的最后一条（Landau-Placzek 1934）
const risOld = fs.readFileSync(SRC + '/气体瑞利-布里渊散射RBS_文献补充.ris', 'utf8').replace(/^\uFEFF/, '');
const blocks = risOld.split(/\n[ \t]*\n/).filter(s => s.trim());
const manual = blocks[blocks.length - 1].replace(/[\r\n]+$/, '');  // 只去行尾换行，保留 RIS 行尾空格，保证与旧文件逐字节一致

const cfg = {
  topic: 'rbs',
  title: '气体瑞利-布里渊散射（RBS）文献补充',
  zotero: { apiBase: 'http://localhost:23119', collectionKey: 'C33', tags: ['RBS-文献补充-2026-09-03'] },
  search: { mailto: 'rbs-lit@example.com', rows: 100, pagesPerQuery: 2, pauseMs: 300, queries: [...q1, ...q2] },
  filter: {
    requireAny: [BR],
    requireContextAny: [GAS, STRONG],
    excludeAny: [FIB],
    rescueAny: [GAS_WORDS],
    secondary: { requireAny: [KEEP], requireContextAny: [GAS], excludeAny: [], rescueAny: [] }
  },
  finalize: { excludeDois: rm },
  export: { risFile: '气体瑞利-布里渊散射RBS_文献补充.ris', extraRis: ['manual_extra.ris'] }
};

writeJson(root('topics', 'rbs.json'), cfg);
writeText(root('outputs', 'rbs', 'approved_dois.txt'),
  '# 审定日期 2026-09-03，来源 rbs_task/finalize.js（84 个 DOI）\n' + dois.join('\n') + '\n');
writeText(root('outputs', 'rbs', 'manual_extra.ris'), manual + '\n');
log(`迁移完成：关键词 ${cfg.search.queries.length} 组 | DOI ${dois.length} 个 | 排除 ${rm.length} 个 | 手工条目 1 条`);
