import { loadConfig, zoteroBase, zoteroAllItems, ensureOut, out, writeJson, log, die } from './lib.mjs';

const topic = process.argv[2];
if (!topic) die('用法: node 01_baseline.mjs <topic>   例: node 01_baseline.mjs rbs');

const cfg = loadConfig(topic);
ensureOut(topic);

log(`[1/7] 摸底：拉取 Zotero 现有库 ${zoteroBase(cfg)}（先确认 Zotero 已打开）`);
const items = await zoteroAllItems(zoteroBase(cfg));
writeJson(out(topic, 'baseline.json'), items);
log(`共 ${items.length} 条，其中带 DOI ${items.filter(x => x.DOI).length} 条 -> baseline.json`);
log('baseline 是后续筛选去重的依据；往库里导入新文献之前必须先跑这一步。');
