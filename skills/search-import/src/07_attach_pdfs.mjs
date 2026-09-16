import { loadConfig, ensureOut, out, readJson, writeJson, log, normDoi, sleep, zoteroBase, zoteroSaveAttachment, directPdfCandidates, die } from './lib.mjs';

const topic = process.argv[2];
if (!topic) die('用法: node 07_attach_pdfs.mjs <topic>');
const cfg = loadConfig(topic);
const base = zoteroBase(cfg);
const email = cfg.search?.mailto || 'user@example.com';
const UA = {
  'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36',
  'Accept': 'application/pdf,text/html;q=0.8,*/*;q=0.5', 'Accept-Language': 'en-US,en;q=0.9'
};
ensureOut(topic);

const imports = readJson(out(topic, 'import_results.json'), null);
if (!imports?.items?.length) die('先跑 06_import.mjs 生成 import_results.json');
const sess = new Map(imports.items.filter(r => r.sessionID).map(r => [normDoi(r.doi), r.sessionID]));

const prev = readJson(out(topic, 'pdf_results.json'), []) || [];
const attached = new Set(prev.filter(r => r.status === 'attached').map(r => normDoi(r.doi)));
const results = prev.filter(r => r.status === 'attached');   // 断点续跑：已挂上的不再动

const targets = [...sess.keys()].filter(d => !attached.has(d));
log(`[7/7] PDF 全文：待处理 ${targets.length} 项（已挂载 ${attached.size}）`);

// 卷期页元数据来自 final_items.json（出版社直链要用）
const finals = new Map((readJson(out(topic, 'final_items.json'), []) || []).map(x => [normDoi(x.doi), x]));

// 顺序：Unpaywall 优先（覆盖面广）-> 出版社直链兜底（Optica OE / MDPI，见 lib.directPdfCandidates）。
// 全程串行，一条处理完再下一条 —— 实践中在入库高峰并发下载附件会把 Zotero 拖崩（有数据库损坏风险）。
for (const doi of targets) {
  let oa = null;
  try {
    const r = await fetch(`https://api.unpaywall.org/v2/${encodeURIComponent(doi)}?email=${email}`, { signal: AbortSignal.timeout(15000) });
    if (r.ok) oa = (await r.json()).best_oa_location;
  } catch { /* 无 OA 或超时 */ }

  const urls = oa ? [oa.url_for_pdf, (/\.pdf(\?|$)/i.test(oa.url || '') ? oa.url : null)] : [];
  urls.push(...directPdfCandidates(finals.get(doi) || {}));
  const cands = [...new Set(urls.filter(Boolean))];
  if (!cands.length) { results.push({ doi, status: 'no-oa' }); persist(); continue; }

  let done = false;
  for (const pdfUrl of cands) {
    try {
      const pr = await fetch(pdfUrl, { signal: AbortSignal.timeout(60000), headers: UA, redirect: 'follow' });
      const buf = Buffer.from(await pr.arrayBuffer());
      if (!(buf.length > 8000 && buf.slice(0, 5).toString('latin1').startsWith('%PDF'))) { log('  not-pdf', doi, buf.length); continue; }
      const sid = sess.get(doi) || `litwf-${topic}-pdf-${doi}`;
      const st = await zoteroSaveAttachment(base, sid, `litwf-${topic}-${doi}`, buf, pdfUrl);
      if (st === 201) { results.push({ doi, status: 'attached', len: buf.length, src: new URL(pdfUrl).host }); log('  ✓', doi, Math.round(buf.length / 1024) + 'KB'); done = true; break; }
      log('  attach fail', doi, st);
    } catch (e) { log('  err', doi, String(e).slice(0, 70)); }
  }
  if (!done) results.push({ doi, status: 'no-oa' });
  persist();
  await sleep(300);
}

const ok = results.filter(r => r.status === 'attached').length;
log(`全文挂载：成功 ${ok} | 无 OA ${results.filter(r => r.status === 'no-oa').length} | 总 ${results.length}`);

function persist() { writeJson(out(topic, 'pdf_results.json'), results); }
