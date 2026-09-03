import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

export const root = (...p) => path.join(ROOT, ...p);
export const sleep = ms => new Promise(r => setTimeout(r, ms));
export const normTitle = s => (s || '').toLowerCase().replace(/[^a-z0-9]+/g, '');
export const normDoi = d => (d || '').replace(/^https?:\/\/doi\.org\//i, '').replace(/^doi:\s*/i, '').trim().toLowerCase();

// ---------- 标题相似度去重（实战验证过的保守二值口径）----------
export const titleTokens = s => new Set((s || '').toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').split(/\s+/).filter(Boolean));
// 判定规则：公共词 >= minInter 且 >= 较短标题词数的 threshold 倍 -> 认定同一篇（返回 1，否则 0）。
// 经验值：threshold=0.8 对泛化短标题误杀偏多，工作流默认用 0.9（见 03）。
export function tokenSim(A, B, { minInter = 5, threshold = 0.8 } = {}) {
  if (!A.size || !B.size) return 0;
  let inter = 0;
  for (const t of A) if (B.has(t)) inter++;
  if (inter >= minInter && inter / Math.min(A.size, B.size) >= threshold) return 1;
  return 0;
}
export const titleSim = (a, b, opts) => tokenSim(titleTokens(a), titleTokens(b), opts);
export const TITLE_SIM_THRESHOLD = 0.9;  // 工作流默认阈值

export function readJson(p, fallback = null) {
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch { return fallback; }
}
export function writeJson(p, data) {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(data, null, 1), 'utf8');
}
export function writeText(p, text) {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, text, 'utf8');
}
export const outDir = topic => root('outputs', topic);
export const out = (topic, name) => path.join(outDir(topic), name);
export function ensureOut(topic) { fs.mkdirSync(outDir(topic), { recursive: true }); return outDir(topic); }

export function loadConfig(topic) {
  const p = root('topics', topic + '.json');
  if (!fs.existsSync(p)) {
    console.error(`配置不存在: ${p}\n先复制 config.example.json 为 topics/${topic}.json，填好关键词和筛选规则。`);
    process.exit(1);
  }
  return JSON.parse(fs.readFileSync(p, 'utf8'));
}

export function stamp() { return new Date().toISOString().replace('T', ' ').slice(0, 19); }
export function log(...a) { console.log(`[${stamp()}]`, ...a); }
export function die(msg) { console.error('[x] ' + msg); process.exit(1); }

export const reAny = list => (Array.isArray(list) && list.length) ? new RegExp(list.join('|'), 'i') : null;

export const CROSSREF_SELECT = 'DOI,title,container-title,short-container-title,issued,author,volume,issue,page,type,publisher,abstract';

export async function fetchJson(url, { tries = 3, pauseMs = 1500, headers = {} } = {}) {
  let last;
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch(url, { headers: { 'User-Agent': 'lit-workflow/1.0', ...headers } });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return await r.json();
    } catch (e) { last = e; if (i < tries - 1) await sleep(pauseMs); }
  }
  throw last;
}

// ---------- Zotero 本地 API ----------
const ITEM_TYPES = ['journalArticle', 'preprint', 'conferencePaper', 'thesis', 'book', 'bookSection', 'report', 'document'];
export const zoteroBase = cfg => (cfg.zotero && cfg.zotero.apiBase) || 'http://localhost:23119';
const ZH = { 'Content-Type': 'application/json', 'X-Zotero-Version': '5.0.111', 'X-Zotero-Connector-API-Version': '3' };

export async function zoteroAllItems(base, types = ITEM_TYPES) {
  const all = [];
  for (const t of types) {
    let start = 0;
    while (true) {
      const j = await fetchJson(`${base}/api/users/0/items?itemType=${t}&limit=100&start=${start}&format=json`, { tries: 5, pauseMs: 2000 });
      if (!Array.isArray(j) || j.length === 0) break;
      for (const it of j) {
        const d = it.data || {};
        all.push({
          key: d.key, type: d.itemType, title: d.title || '', DOI: normDoi(d.DOI),
          creators: (d.creators || []).map(c => ((c.lastName || '') + ' ' + (c.firstName || '')).trim()).slice(0, 3).join(';'),
          date: d.date || '', pub: d.publicationTitle || d.proceedingsTitle || d.publisher || ''
        });
      }
      if (j.length < 100) break;
      start += 100;
    }
  }
  return all;
}

export async function zoteroSaveItems(base, sessionID, items) {
  const r = await fetch(base + '/connector/saveItems', { method: 'POST', headers: ZH, body: JSON.stringify({ sessionID, items }) });
  return { status: r.status, body: (await r.text()).slice(0, 300) };
}
export const zoteroSaveItem = (base, sessionID, item) => zoteroSaveItems(base, sessionID, [item]);

export async function zoteroUpdateSession(base, sessionID, target, tags) {
  const r = await fetch(base + '/connector/updateSession', { method: 'POST', headers: ZH, body: JSON.stringify({ sessionID, target, tags }) });
  return { status: r.status, body: (await r.text()).slice(0, 200) };
}

export async function zoteroSaveAttachment(base, sessionID, parentItemID, buf, url) {
  const meta = JSON.stringify({ sessionID, parentItemID, title: 'Full Text PDF', url });
  const r = await fetch(base + '/connector/saveAttachment?sessionID=' + encodeURIComponent(sessionID),
    { method: 'POST', headers: { ...ZH, 'Content-Type': 'application/pdf', 'X-Metadata': meta }, body: buf });
  return r.status;
}

// final_items 记录 → Zotero 条目
export function toZoteroItem(x, topic) {
  const clean = s => (s || '').replace(/&amp;/g, '&').replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/\s+/g, ' ').trim();
  let itemType = 'journalArticle'; const o = {};
  if (x.type === 'proceedings-article') { itemType = 'conferencePaper'; o.proceedingsTitle = clean(x.journal); o.conferenceName = clean(x.journal); if (x.publisher) o.publisher = clean(x.publisher); }
  else if (x.type === 'book-chapter') { itemType = 'bookSection'; o.bookTitle = clean(x.journal); if (x.publisher) o.publisher = clean(x.publisher); }
  else if (x.type === 'posted-content') { itemType = 'conferencePaper'; o.proceedingsTitle = clean(x.journal) || 'Preprint/Abstract'; o.conferenceName = clean(x.journal) || 'Preprint/Abstract'; }
  else { o.publicationTitle = clean(x.journal); if (x.shortjournal) o.journalAbbreviation = clean(x.shortjournal); }
  const creators = (x.authors || []).filter(a => a.family || a.given).map(a => {
    const fam = clean(a.family), giv = clean(a.given);
    return giv ? { firstName: giv, lastName: fam, creatorType: 'author' } : { lastName: fam, firstName: '', fieldMode: 1, creatorType: 'author' };
  });
  const it = { id: `litwf-${topic}-${x.doi}`, itemType, title: clean(x.title), creators, date: x.year ? (x.month ? `${x.year}-${String(x.month).padStart(2, '0')}` : String(x.year)) : '', tags: [], ...o };
  if (x.volume) it.volume = x.volume; if (x.issue) it.issue = x.issue; if (x.page) it.pages = x.page;
  it.DOI = x.doi; it.url = 'https://doi.org/' + x.doi;
  if (x.abstract) it.abstractNote = clean(x.abstract).slice(0, 2000);
  return it;
}

// ---------- BibTeX 导出 ----------
export function bibKey(x) {
  const fam = ((x.authors?.[0]?.family) || 'Unknown').replace(/[^A-Za-z]/g, '') || 'Unknown';
  const kw = [...titleTokens(x.title)].slice(0, 3).join('_') || 'paper';
  return `${fam}_${x.year || 'nd'}_${kw}`;
}
export function toBibtex(x) {
  const etype = x.type === 'proceedings-article' ? 'inproceedings' : x.type === 'book-chapter' ? 'inbook' : 'article';
  const L = [`@${etype}{${bibKey(x)},`];
  const auth = (x.authors || []).filter(a => a.family || a.given)
    .map(a => a.given ? `${a.family}, ${a.given}` : (a.family || '')).join(' and ');
  if (auth) L.push(`  author = {${auth}},`);
  L.push(`  title = {${x.title}},`);
  if (etype === 'article') L.push(`  journal = {${x.journal || ''}},`);
  else L.push(`  booktitle = {${x.journal || x.publisher || 'Proceedings'}},`);
  if (x.year) L.push(`  year = {${x.year}},`);
  if (x.volume) L.push(`  volume = {${x.volume}},`);
  if (x.issue) L.push(`  number = {${x.issue}},`);
  if (x.page) L.push(`  pages = {${String(x.page).replace('-', '--')}},`);
  L.push(`  doi = {${x.doi}},`);
  if (x.publisher) L.push(`  publisher = {${x.publisher}},`);
  if (x.abstract) L.push(`  abstract = {${String(x.abstract).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()}},`);
  L.push('}');
  return L.join('\n');
}

// ---------- 出版社直链 PDF（Unpaywall 覆盖不到时的兜底，可按同样套路扩展更多出版社）----------
const MDPI_ISSN = { s: '1424-8220', app: '2076-3417', photonics: '2304-6732' }; // sensors / applied sciences / photonics
export function directPdfCandidates(x) {
  const doi = normDoi(x.doi), urls = [];
  if (doi.startsWith('10.1364/oe.')) {           // Optica Optics Express: 用卷/期/首页拼直链
    const pg = String(x.page || '').split('-')[0];
    if (x.volume && x.issue && pg) urls.push(`https://opg.optica.org/oe/viewmedia.cfm?uri=oe-${x.volume}-${x.issue}-${pg}&seq=0`);
  }
  const m = doi.match(/^10\.3390\/([a-z]+)(\d)(\d)(\d+)$/);   // MDPI: DOI 里编码了卷期与文章号
  if (m) {
    const issn = MDPI_ISSN[m[1]];
    if (issn) urls.push(`https://www.mdpi.com/${issn}/${m[2]}/${m[3]}/${m[4]}/pdf`);
  }
  return urls;
}
