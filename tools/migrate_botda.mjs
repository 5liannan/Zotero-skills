// 从 BOTDA_literature（Python 一次性管线）机械迁移到本工作流：
//   生成 topics/botda.json + outputs/botda/curated.json（人工注记）+ outputs/botda/approved_dois.txt（已审定清单）
// 用法: node tools/migrate_botda.mjs [源目录]
//   默认源目录 C:\Users\Administrator\Desktop\BOTDA_literature（含 records.json / curated.json）
// 只做纯本地搬移，不联网。
import { root, out, readJson, writeJson, writeText, normDoi, ensureOut, log } from '../src/lib.mjs';

const SRC = process.argv[2] || 'C:\\Users\\Administrator\\Desktop\\BOTDA_literature';
const EXCLUDED = new Set(['10.1109/50.32379']); // BOTDA 项目中人工剔出的错误 DOI（色散论文）

const records = readJson(`${SRC}\\records.json`, null);
const curatedSrc = readJson(`${SRC}\\curated.json`, null);
if (!records?.length) { console.error(`[x] 读不到 ${SRC}\\records.json`); process.exit(1); }

// 检索词 = BOTDA 发现阶段的 5 组查询 + 18 组经典文献标题探测查询
const QUERIES = [
  'Brillouin optical time domain analysis',
  'BOTDA Brillouin',
  'vector Brillouin optical time domain analysis',
  'Brillouin distributed fiber sensing review',
  'Brillouin optical time domain analysis sensor',
  'BOTDA-nondestructive measurement of single-mode optical fiber attenuation characteristics using Brillouin interaction: simulation and experiment',
  'A technique to measure distributed strain in optical fibers',
  'Combined distributed temperature and strain sensor based on Brillouin loss in an optical fiber',
  'Experimental and theoretical studies on a distributed temperature sensor based on Brillouin scattering',
  'Development of a distributed sensing technique using Brillouin scattering',
  'Brillouin gain spectrum characterization in single-mode optical fibers',
  'Pulse width dependence of the Brillouin loss spectrum in single-mode fiber',
  'Signal processing for a high-spatial-resolution distributed fiber optic sensor',
  'Distributed fiber-optic sensor based on dark-pulse Brillouin scattering',
  'Pulse pre-pump method for high-resolution Brillouin distributed measurement system',
  'High spatial and spectral resolution long-range sensing using Brillouin echoes',
  'Fast Brillouin optical time domain analysis for dynamic sensing',
  'Random-access distributed Brillouin fiber sensor',
  'Time-division multiplexing-based BOTDA over 100 km sensing length',
  'Distributed Brillouin fiber sensing: recent advances toward pragmatic applications',
  'Modeling and evaluating the performance of Brillouin distributed optical fiber sensors',
  'Intensifying the response of distributed optical fibre sensors using 2D and 3D image restoration',
  'Brillouin distributed time-domain sensing in optical fibers: state of the art and perspectives',
];

// 经典文献 DOI 直取清单（botda_collect.py 的 PROBE_DOIS）
const DOIS = [
  '10.1364/OL.15.001038', '10.1364/OL.18.001561', '10.1364/OL.21.000758', '10.1364/OE.21.031347',
  '10.1038/ncomms10870', '10.1155/2010/136912', '10.3390/s110404152', '10.3390/s120708681',
  '10.3390/s16050748', '10.1109/50.32378',
];

const cfg = {
  topic: 'botda',
  title: '布里渊光时域分析（BOTDA）文献检索与导入',
  zotero: {
    apiBase: 'http://localhost:23119',
    collectionKey: '',          // 按需填写：Zotero 里 BOTDA 分类右键 -> 显示 Key
    tags: ['BOTDA-文献补充'],
  },
  search: {
    mailto: 'research.botda.collector@gmail.com',
    rows: 50,
    pagesPerQuery: 2,
    pauseMs: 300,
    queries: QUERIES,
    dois: DOIS,
  },
  filter: {
    // BOTDA 原管线是"人工圈定清单"驱动，不做正则过滤；这里只留一道护栏
    requireAny: ['brillouin'],
    excludeAny: [],
    rescueAny: [],
    simInLibrary: true,
  },
  finalize: {
    excludeDois: [...EXCLUDED],
  },
  export: {
    risFile: 'BOTDA_文献补充.ris',
    extraRis: [],
  },
  report: {
    title: '布里渊光时域分析（BOTDA）文献报告',
    defaultCategory: '关键技术里程碑',
    categories: [   // 顺序即优先级：先看综述，再看奠基，其余落默认类（对应 BOTDA finalize.py）
      { name: '综述与评述', noteAny: ['综述'] },
      { name: '奠基性经典（1989-2005）', noteAny: ['首', '首创', '前身', '1989', '1990', '1993', '1994', '1995', '1996', '1997', '2000', '2005'] },
    ],
  },
};

writeJson(root('topics', 'botda.json'), cfg);

// 人工注记：原样搬移（08_report.mjs 按 note 关键词归类）
const curated = (curatedSrc || []).map(c => ({ doi: normDoi(c.doi), note: c.note || '' })).filter(c => c.doi);
ensureOut('botda');
writeJson(out('botda', 'curated.json'), curated);

// 已审定 DOI 清单：records.json 就是当年人工圈定的成果，直接作为 approved_dois.txt，
// 之后跑 04 -> 05/06 -> 07 -> 08 全程无需重新人工圈选
const dois = [...new Set(records.map(r => normDoi(r.doi)).filter(d => d && !EXCLUDED.has(d)))];
writeText(out('botda', 'approved_dois.txt'),
  `# BOTDA 已审定清单：由 tools/migrate_botda.mjs 从 records.json 机械迁移（${dois.length} 条）\n` + dois.join('\n') + '\n');

log(`迁移完成：topics/botda.json | outputs/botda/curated.json（${curated.length} 条注记）| outputs/botda/approved_dois.txt（${dois.length} 个 DOI）`);
log(`源记录 ${records.length} 条，其中剔除 ${[...EXCLUDED].filter(d => records.some(r => normDoi(r.doi) === d)).length} 条已写进 finalize.excludeDois`);
