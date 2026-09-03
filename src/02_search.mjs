import { loadConfig, ensureOut, out, readJson, writeJson, log, normDoi, sleep, fetchJson, CROSSREF_SELECT, die } from './lib.mjs';

const topic = process.argv[2];
if (!topic) die('用法: node 02_search.mjs <topic>');
const cfg = loadConfig(topic);
const S = cfg.search;
if (!S || (!(S.queries?.length) && !(S.dois?.length))) die('config.search 里没有 queries 或 dois');
ensureOut(topic);

const prev = readJson(out(topic, 'candidates_all.json'), []) || [];
const pool = new Map(prev.map(c => [normDoi(c.doi), c]));
log(`[2/7] 抓取 Crossref。已有候选 ${pool.size} 条（重跑自动合并去重，可断点续抓）`);

const meta = [];
for (const item of S.queries) {
  const q = typeof item === 'string' ? { q: item } : item;
  let cursor = '*', fetched = 0, added = 0;
  for (let page = 0; page < (S.pagesPerQuery ?? 2); page++) {
    const url = `https://api.crossref.org/works?query.bibliographic=${encodeURIComponent(q.q)}`
      + `&rows=${S.rows ?? 100}&select=${encodeURIComponent(CROSSREF_SELECT)}&mailto=${S.mailto}`
      + (q.filter ? `&filter=${encodeURIComponent(q.filter)}` : '')
      + `&cursor=${encodeURIComponent(cursor)}`;
    let j;
    try { j = await fetchJson(url, { headers: { 'User-Agent': `lit-workflow/1.0 (mailto:${S.mailto})` } }); }
    catch (e) { log('  ERR', q.q, e.message); break; }
    const items = j?.message?.items || [];
    fetched += items.length;
    for (const it of items) {
      const doi = normDoi(it.DOI), title = ((it.title && it.title[0]) || '').replace(/<[^>]+>/g, '');
      if (!doi || !title || pool.has(doi)) continue;
      pool.set(doi, {
        doi, title,
        journal: (it['container-title'] && it['container-title'][0]) || '',
        year: (it.issued?.['date-parts']?.[0]?.[0]) || '',
        authors: (it.author || []).map(a => ((a.given || '') + ' ' + (a.family || '')).trim()).join('; '),
        volume: it.volume || '', issue: it.issue || '', page: it.page || '',
        type: it.type || '', publisher: it.publisher || '',
        abstract: ((it.abstract || '').replace(/<[^>]+>/g, ' ')).slice(0, 600),
        source: q.q
      });
      added++;
    }
    cursor = j?.message?.['next-cursor'];
    if (!cursor || items.length < (S.rows ?? 100)) break;
    await sleep(S.pauseMs ?? 300);
  }
  meta.push({ q: q.q, filter: q.filter || '', fetched, added });
  log(`  +${added} (抓到 ${fetched})  "${q.q}"`);
  await sleep(S.pauseMs ?? 300);
}

// 直取 DOI（BOTDA 经验：探测清单里的经典文献用标题搜索可能漏，按 DOI 拉最可靠）
for (const d of S.dois || []) {
  const doi = normDoi(d);
  if (!doi) continue;
  if (pool.has(doi)) { meta.push({ q: `DOI:${doi}`, fetched: 0, added: 0, note: 'already-in-pool' }); continue; }
  let added = 0;
  try {
    const j = await fetchJson(`https://api.crossref.org/works/${encodeURIComponent(doi)}?select=${encodeURIComponent(CROSSREF_SELECT)}&mailto=${S.mailto}`,
      { headers: { 'User-Agent': `lit-workflow/1.0 (mailto:${S.mailto})` } });
    const it = j.message;
    const title = ((it.title && it.title[0]) || '').replace(/<[^>]+>/g, '');
    if (title) {
      pool.set(doi, {
        doi, title,
        journal: (it['container-title'] && it['container-title'][0]) || '',
        year: (it.issued?.['date-parts']?.[0]?.[0]) || '',
        authors: (it.author || []).map(a => ((a.given || '') + ' ' + (a.family || '')).trim()).join('; '),
        volume: it.volume || '', issue: it.issue || '', page: it.page || '',
        type: it.type || '', publisher: it.publisher || '',
        abstract: ((it.abstract || '').replace(/<[^>]+>/g, ' ')).slice(0, 600),
        source: 'DOI直取'
      });
      added = 1;
    }
  } catch { /* 404 等视为该 DOI 不可用，落 meta 即可 */ }
  meta.push({ q: `DOI:${doi}`, fetched: 1, added });
  log(`  +${added}  DOI:${doi}`);
  await sleep(S.pauseMs ?? 300);
}

writeJson(out(topic, 'candidates_all.json'), [...pool.values()]);
writeJson(out(topic, 'candidates_meta.json'), meta);
log(`候选池共 ${pool.size} 条 -> candidates_all.json（每组查询的命中数另见 candidates_meta.json）`);
