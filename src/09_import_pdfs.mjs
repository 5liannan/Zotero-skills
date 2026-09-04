import fs from 'node:fs';
import path from 'node:path';
import {
  loadConfig, ensureOut, out, readJson, writeJson, writeText, log, normDoi, sleep,
  zoteroBase, zoteroAllItems, zoteroPdfParents, zoteroSaveItem, zoteroSaveAttachment,
  zoteroSaveStandaloneAttachment, zoteroRecognizedItem, zoteroUpdateSession, zoteroTargets, resolveTarget,
  toZoteroItem, pdfExtract, doiFromFilename, crossrefByDoi, crossrefByTitle, titleSim, titleTokens, die
} from './lib.mjs';

// 09 本地全文 PDF 入库：扫描目录 -> 从 PDF 里抽 DOI/标题 -> 查库去重 -> 补元数据 -> 导入 Zotero
//
// 关于「为什么不能挂到已有条目上」：Zotero 只开放了两类写接口——本地 API 是只读的（官方源码
// server_localAPI.js 里写明 Write access is not yet supported），连接器接口 /connector/saveAttachment
// 的 parentItemID 只认本次会话里 saveItems 建出来的临时 id（saveSession.js 的 getItemByConnectorKey
// 就是查会话自己的 map）。所以本地 PDF 只能「新建条目 + 连同 PDF 一起存」，不能补附件到旧条目。
// 因此默认策略是：库里已经有这篇就跳过并列出清单，避免重复条目。

const topic = process.argv[2];
if (!topic) die('用法: node 09_import_pdfs.mjs <topic> [--dir <PDF目录>] [--dry] [--force] [--limit N]');
const argv = process.argv.slice(3);
const has = f => argv.includes('--' + f);
const val = f => { const i = argv.indexOf('--' + f); return i >= 0 ? argv[i + 1] : null; };

const cfg = loadConfig(topic);
const base = zoteroBase(cfg);
const P = cfg.pdf || {};
const mailto = cfg.search?.mailto || 'user@example.com';
const dir = val('dir') || P.dir;
if (!dir) die(`缺少 PDF 目录：node 09_import_pdfs.mjs ${topic} --dir <路径>，或在 topics/${topic}.json 里配 pdf.dir`);
if (!fs.existsSync(dir)) die('目录不存在: ' + dir);
const limit = Number(val('limit') || 0) || 0;
ensureOut(topic);

// ---------- 扫描 ----------
function scanPdfs(root, recursive) {
  const list = [];
  const walk = d => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) { if (recursive !== false) walk(p); }
      else if (/\.pdf$/i.test(e.name)) list.push(p);
    }
  };
  walk(root);
  return list.sort();
}
let files = scanPdfs(dir, P.recursive);
if (limit) files = files.slice(0, limit);
log(`[9/9] 本地全文入库：目录 ${dir} 共 ${files.length} 个 PDF${has('dry') ? '（--dry 只预览，不写入 Zotero）' : ''}`);

// ---------- 库内索引（去重用；Zotero 离线时降级，dry-run 照常预览）----------
async function safeZoteroCall(fn, fallback, what) {
  try { return await fn(); }
  catch (e) {
    const msg = (e.cause && e.cause.code) || e.code || e.message;
    log(`! ${what} 失败（${msg}），已降级${has('dry') ? '；dry-run 不影响预览' : '——本轮略过库内查重'}`);
    return fallback;
  }
}
const libItems  = await safeZoteroCall(() => zoteroAllItems(base), [], '拉取 Zotero 库条目');
const libByDoi  = new Map(libItems.filter(x => x.DOI).map(x => [x.DOI, x]));
const libTokens = libItems.filter(x => x.title).map(x => ({ ...x, tok: titleTokens(x.title) }));
const hasPdf    = await safeZoteroCall(() => zoteroPdfParents(base), new Set(), '查 Zotero 已挂 PDF 条目');
log(`库内现有条目 ${libItems.length} 条，其中 ${hasPdf.size} 条已有 PDF 附件`);

// 07 阶段没拿到全文的条目（能补上就在结果里标出来）
const noOa = new Set((readJson(out(topic, 'pdf_results.json'), []) || []).filter(r => r.status === 'no-oa').map(r => normDoi(r.doi)).filter(Boolean));

// 本主题已定稿的元数据（有就直接复用，省一次 Crossref 往返）
const finals = new Map((readJson(out(topic, 'final_items.json'), []) || []).map(x => [normDoi(x.doi), x]));

// ---------- 断点续跑 ----------
const resultsFile = out(topic, 'pdf_import.json');
const prev = readJson(resultsFile, []) || [];
const doneFile = new Set(prev.filter(r => r.status === 'imported').map(r => r.file));
const results = prev.filter(r => r.status === 'imported');
let skipped = results.length;

// ---------- 归档目标 ----------
const targets = await safeZoteroCall(() => zoteroTargets(base), [], '读 Zotero 分类树');
const wantTarget = P.collection || cfg.zotero?.collectionKey || '';
const target = resolveTarget(targets, wantTarget) || targets.find(t => /^L\d+$/.test(t.id))?.id || 'L1';
if (wantTarget && !resolveTarget(targets, wantTarget)) log(`  ! 配置里的分类「${wantTarget}」在 Zotero 里找不到（要写成 C<数字> 或分类全名），本轮落到 ${target}`);
const tags = P.tags || cfg.zotero?.tags || [];
log(`归档目标 ${target}${tags.length ? '，标签 ' + tags.join(' / ') : ''}`);

// ---------- 工具 ----------
const cleanName = n => (n || '').replace(/\.pdf$/i, '')
  .replace(/^[^一-龥A-Za-z]*/, '')
  .replace(/^[^一-龥]{0,40}?\s+等\s*-\s*\d{4}\s*-\s*/, '')   // 去掉 Zotero 风格的 "Liang 等 - 2022 - "
  .replace(/\s+/g, ' ').trim();
// 标题可信度兜底：Crossref 命中的条目和 PDF 元数据标题差太远，多半是 DOI 抽错了
function suspicious(pdfTitle, metaTitle) {
  const a = titleTokens(pdfTitle), b = titleTokens(metaTitle);
  const latin = s => [...s].filter(t => /[a-z0-9]/.test(t)).length;
  if (latin(a) < 4 || latin(b) < 4) return false;        // 中文标题没法比，不据此否定
  return !titleSim(pdfTitle, metaTitle, { minInter: 4, threshold: 0.5 });
}

let i = 0, ok = 0, fail = 0;
for (const file of files) {
  i++;
  if (doneFile.has(file)) continue;
  const name = path.basename(file);
  const rec = { file, name, doi: '', title: '', status: '', meta: '', matched: '', from: '' };
  let buf;
  try { buf = fs.readFileSync(file); } catch { rec.status = 'read-error'; results.push(rec); continue; }
  rec.size = buf.length;

  // 1) 抽 DOI / 标题
  if (!buf.slice(0, 5).toString('latin1').startsWith('%PDF')) {
    rec.status = 'not-pdf'; results.push(rec); persist(); continue;
  }
  const ex = pdfExtract(buf);
  rec.title = ex.title || cleanName(name);
  rec.doi = normDoi(ex.doi || doiFromFilename(name));
  rec.from = ex.doi ? ex.doiFrom : (rec.doi ? 'filename' : '');

  // 2) 查库去重：DOI 精确优先，其次标题相似
  let hit = rec.doi ? libByDoi.get(rec.doi) : null;
  if (!hit && rec.title) hit = libTokens.find(x => titleSim(rec.title, x.title, { minInter: 5, threshold: 0.95 })) || null;
  if (hit && !has('force')) {
    rec.status = hasPdf.has(hit.key) ? 'in-library-with-pdf' : 'in-library-no-pdf';
    rec.matched = `${hit.key} | ${hit.title}`;
    results.push(rec); persist();
    log(`  ${rec.status === 'in-library-with-pdf' ? '已有全文' : '已在库  '} ${rec.status === 'in-library-with-pdf' ? '·跳过' : '·待补'} ${rec.doi || rec.title.slice(0, 40)}`);
    continue;
  }

  // 3) 补元数据：本主题定稿 -> Crossref by DOI -> Crossref by 标题
  let meta = rec.doi ? finals.get(rec.doi) : null;
  if (meta) rec.meta = 'final_items';
  if (!meta && rec.doi) {
    try { meta = await crossrefByDoi(rec.doi, mailto); } catch { /* 404 或超时 */ }
    if (meta && suspicious(rec.title, meta.title)) { log(`  ! DOI 元数据与 PDF 标题对不上，放弃该 DOI: ${rec.doi}`); meta = null; }
    if (meta) rec.meta = 'crossref-doi';
  }
  if (!meta && P.crossrefFallback !== false && rec.title.length >= 12) {
    try { meta = await crossrefByTitle(rec.title, mailto); } catch { /* 同上 */ }
    if (meta) { rec.meta = 'crossref-title'; rec.doi = normDoi(meta.doi); }
  }

  if (has('dry')) {
    rec.status = meta ? 'would-import' : 'would-recognize';
    results.push(rec); persist();
    log(`  [dry] ${rec.status} ${(meta?.title || rec.title || '').slice(0, 60)} | ${rec.doi || '无 DOI'}`);
    continue;
  }

  // 4) 导入。全程串行，一条处理完再下一条 —— 并发写附件会把 Zotero 拖崩（07 已踩过）
  const sid = `litpdf-${topic}-${i}`;
  try {
    if (meta) {
      // 有新条目元数据：我们自己建条目，再把本地 PDF 字节当附件塞进去
      const item = toZoteroItem(meta, topic);
      item.id = sid;
      const r = await zoteroSaveItem(base, sid, item);
      if (r.status !== 201) throw new Error('saveItems ' + r.status + ' ' + r.body);
      await sleep(400);
      const st = await zoteroSaveAttachment(base, sid, sid, buf, '');
      if (st !== 201) throw new Error('saveAttachment ' + st);
      rec.status = 'imported'; rec.doi = normDoi(meta.doi); rec.title = meta.title;
    } else {
      // 没元数据：交给 Zotero 自己识别 PDF（需要联网，识别不出来就是一条独立 PDF 条目）
      const r = await zoteroSaveStandaloneAttachment(base, sid, name, buf);
      if (r.status !== 201) throw new Error('saveStandaloneAttachment ' + r.status + ' ' + r.body);
      if (r.canRecognize) {
        await sleep(2500);
        const got = await zoteroRecognizedItem(base, sid);
        if (got.status === 200) { try { rec.title = JSON.parse(got.body).title || rec.title; } catch { /* 忽略 */ } }
      }
      rec.status = 'imported'; rec.meta = rec.meta || 'zotero-recognize';
    }
    const u = await zoteroUpdateSession(base, sid, target, tags);
    if (u.status !== 200) log(`  ! updateSession 失败 ${sid} ${u.status}（条目已入库，只是没归到分类）`);
    if (noOa.has(rec.doi)) rec.fillNoOa = true;
    ok++;
    log(`  ✓ ${String(ok).padStart(3)} [${rec.meta || 'recognize'}] ${rec.title.slice(0, 62)}${rec.fillNoOa ? '  ← 补上了 07 没拿到的全文' : ''}`);
  } catch (e) {
    fail++; rec.status = 'failed'; rec.error = String(e.message || e).slice(0, 160);
    log(`  x ${name.slice(0, 50)} ${rec.error}`);
  }
  results.push(rec); persist();
  await sleep(300);
}
persist();

// ---------- 汇总 ----------
const by = {};
for (const r of results) by[r.status] = (by[r.status] || 0) + 1;
log('\n本地 PDF 入库：' + Object.entries(by).map(([k, v]) => `${k} ${v}`).join(' | '));
log(`本轮新增 ${ok} 条${fail ? `，失败 ${fail} 条` : ''}，累计已入库 ${results.filter(r => r.status === 'imported').length} 条`);

// 库里已有条目但缺全文的：连接器接口补不了附件，只能手动拖，列成清单
const need = results.filter(r => r.status === 'in-library-no-pdf');
if (need.length) {
  writeText(out(topic, 'pdf_existing.txt'), [
    '# 这些 PDF 对应的条目已在 Zotero 里，但没有全文附件',
    '# Zotero 的写接口只能新建条目、不能给已有条目加附件，所以请手动拖：',
    '#   在 Zotero 里找到条目（右边是 key/标题）-> 把文件拖进条目即可',
    ...need.map(r => `${r.file}\t${r.matched}`)
  ].join('\n'));
  log(`已在库但缺全文 ${need.length} 个 -> outputs/${topic}/pdf_existing.txt（需手动挂，接口做不到）`);
}
log(`明细：outputs/${topic}/pdf_import.json`);

function persist() { writeJson(resultsFile, results); }
