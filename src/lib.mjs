import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
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

// ---------- 本地 PDF 解析（零依赖：zlib 解压 Flate 流 + 正则提取 DOI/标题）----------
// 为什么不用 pdf 类库：本工作流坚持零 npm 依赖。实测出版社 PDF 的 DOI 绝大多数能在
// XMP 元数据或首页文本里拿到，够用；拿不到的走标题匹配或交给 Zotero 自动识别。
export const DOI_RE = /10\.\d{4,9}\/[A-Za-z0-9._\-/()]+/gi;

const PDF_UNESCAPE = { n: '\n', r: '\r', t: '\t', b: '\b', f: '\f', '(': '(', ')': ')', '\\': '\\' };
const unescapePdf = s => s.replace(/\\([nrtbf()\\])/g, (m, c) => PDF_UNESCAPE[c] ?? c);

function hexToText(hex) {
  const bytes = hex.replace(/\s+/g, '').match(/../g) || [];
  if (bytes.length < 2) return '';
  const nulls = bytes.filter(b => b === '00').length;
  if (bytes.length > 4 && nulls > bytes.length / 4) {          // 带 BOM 的 UTF-16BE，换序后按 utf16le 解
    const swapped = [];
    for (let i = 0; i + 1 < bytes.length; i += 2) swapped.push(bytes[i + 1], bytes[i]);
    return Buffer.from(swapped.join(''), 'hex').toString('utf16le');
  }
  return Buffer.from(bytes.join(''), 'hex').toString('latin1');
}

// 从内容流里抠文本：字面串 (...) 与十六进制串 <...>，按出现顺序拼接
function streamToText(s) {
  let out = '';
  const re = /\(((?:\\.|[^\\()])*)\)|<([0-9A-Fa-f\s]+)>/g;
  let m;
  while ((m = re.exec(s)) !== null) out += m[1] !== undefined ? unescapePdf(m[1]) : hexToText(m[2]);
  return out;
}

// DOI 尾部清理：PDF 里 DOI 常与后面的单词直接连写（实测：'...748AcademicEditor:'、
// '...465.digitalobjectidentifier:'、'...018*corresponding'），中间没有任何分隔符。
// 因此在「数字后紧跟 6+ 字母」或「点号后紧跟 8+ 字母」处切断；真实 DOI 不会命中这两条
// （10.1103/physrevlett.114.243902、10.1016/j.optcom.2004.05.018 里的字母串前面是 / 或 . 后不足 8 位）。
// 仍不放心的地方交给下游：入库前会用 Crossref 校验，404 就退回标题检索，不会拿错 DOI 建条目。
function cleanDoiTail(d) {
  let s = (d || '').trim().replace(/[.,;)\]}"']+$/, '');
  if (!/^10\.\d{4,9}\//.test(s)) return '';
  let at = s.search(/(?<=\d)[A-Za-z]{6,}|(?<=\.)[A-Za-z]{8,}/);
  if (at < 0) at = s.search(/(?<=\d)[A-Za-z]{4,}$/);       // 结尾粘连的短词，如 '...477view'
  if (at > 0) s = s.slice(0, at);
  return s.replace(/[.\-_/]+$/, '');
}

// 从一段文本里挑 DOI：优先带 doi.org / DOI: 前缀的（首页声明），其次裸 DOI
function pickDoi(text) {
  if (!text) return '';
  const near = text.match(/(?:doi\.org\/|doi:\s*|\bDOI\s*[:：]?\s*)(10\.\d{4,9}\/[A-Za-z0-9._\-/()]+)/i);
  return cleanDoiTail(near ? near[1] : (text.match(DOI_RE) || [''])[0]);
}

// 从文件名里挑 DOI：常见命名 10.1016_j.yofte.2021.102783.pdf / 10.1364_OE.24.012345.pdf
export function doiFromFilename(name) {
  const base = (name || '').replace(/\.pdf$/i, '');
  const m = base.match(/10[._-]\d{4,9}[._-][A-Za-z0-9._()+\-]+$/);
  if (!m) return '';
  return normDoi(m[0].replace(/[._-](?=\d{4,9}[._-])/, '.').replace(/[_-]/g, '/')).replace(/[.,;)$]+$/, '');
}

/**
 * 解析本地 PDF，抽取 { doi, doiFrom, title, text }
 * 顺序：XMP 元数据 -> 解压后的首页文本 -> 文件名。text 只取前缀，避免参考文献区的 DOI 误命中。
 */
// 实测（本人库内 34 个真实 PDF）：默认参数 DOI 命中率 59%，放宽到下面的值提到 68%。
// 代价是会把参考文献区的 DOI 也算进来，所以下游必须用 Crossref 校验一遍再建条目。
export function pdfExtract(buf, { textLimit = 30000, maxStreams = 300, doiWindow = 30000, maxStreamBytes = 3e6 } = {}) {
  const out = { doi: '', doiFrom: '', title: '', text: '' };
  if (!buf || buf.length < 200 || !buf.slice(0, 5).toString('latin1').startsWith('%PDF')) return out;
  const raw = buf.toString('latin1');

  // 1) XMP：多数出版社（Wiley / IEEE / Optica / Springer）把 DOI 明文写在这里
  const xmp = (raw.match(/<x(?:ap)?:xmpmeta[\s\S]*?<\/x(?:ap)?:xmpmeta>/i) || [''])[0];
  if (xmp) {
    // 优先结构化的 <dc:identifier>，它比整段 XMP 上跑正则干净得多
    for (const m of xmp.matchAll(/<dc:identifier>([\s\S]*?)<\/dc:identifier>/gi)) {
      const d = cleanDoiTail((m[1].replace(/<[^>]+>/g, '').match(DOI_RE) || [''])[0]);
      if (d) { out.doi = normDoi(d); out.doiFrom = 'xmp'; break; }
    }
    if (!out.doi) { const d = normDoi(pickDoi(xmp)); if (d) { out.doi = d; out.doiFrom = 'xmp'; } }
    const t = xmp.match(/<dc:title>([\s\S]*?)<\/dc:title>/i);
    if (t) out.title = (t[1].match(/<rdf:li[^>]*>([\s\S]*?)<\/rdf:li>/i)?.[1] || t[1]).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
  }

  // 2) 解压 Flate 流：XMP 有时也被压缩，首页文本里的 DOI 声明同样靠它
  let text = '', n = 0;
  const re = /stream\r?\n?([\s\S]*?)endstream/g;
  let m;
  while ((m = re.exec(raw)) !== null && n < maxStreams && text.length < textLimit) {
    n++;
    if (m[1].length > maxStreamBytes) continue;          // 图片流，解压只是白烧 CPU
    let dec;
    try { dec = zlib.inflateSync(Buffer.from(m[1], 'latin1')).toString('latin1'); }
    catch { try { dec = zlib.inflateRawSync(Buffer.from(m[1], 'latin1')).toString('latin1'); } catch { continue; } }
    if (!dec) continue;
    if (!out.doi && /<x(?:ap)?:xmpmeta/i.test(dec)) {          // 压缩的 XMP
      const d = normDoi(pickDoi(dec));
      if (d) { out.doi = d; out.doiFrom = 'xmp-stream'; }
    }
    text += streamToText(dec);
  }
  out.text = text.slice(0, textLimit);

  // 只在首页文本里找裸 DOI：参考文献区的 DOI 长得一模一样，往后会误命中
  if (!out.doi) { const d = normDoi(pickDoi(text.slice(0, doiWindow))); if (d) { out.doi = d; out.doiFrom = 'text'; } }

  // 3) 标题：XMP 没有就退回 PDF 文档属性 /Title（常是 Logo/字体名之类，靠 sanitizeTitle 兜底）
  if (!out.title) {
    const t = raw.match(/\/Title\s*\((?:\\.|[^\\()])*\)/);
    if (t) out.title = unescapePdf(t[0].replace(/^\/Title\s*\(/, '').replace(/\)$/, '')).replace(/\s+/g, ' ').trim();
  }
  out.title = sanitizeTitle(out.title);
  return out;
}

// 去掉控制字符与纯符号噪声，太短或没有实质内容的直接判为无效标题
export function sanitizeTitle(s) {
  const t = (s || '').replace(/[\u0000-\u001f\u007f-\u009f]+/g, ' ').replace(/\s+/g, ' ').trim();
  return /[0-9A-Za-z\u4e00-\u9fa5]{4,}/.test(t) ? t : '';
}

// ---------- Zotero 连接器：本地 PDF 入库 ----------
export async function zoteroPost(base, p, obj, headers = ZH) {
  const r = await fetch(base + p, { method: 'POST', headers, body: JSON.stringify(obj) });
  return { status: r.status, body: (await r.text()).slice(0, 400) };
}

// 独立附件入库：Zotero 7 会自动识别 PDF 元数据（/connector/saveStandaloneAttachment）。
// 注意 sessionID 必须是全新的，已存在会返回 409 SESSION_EXISTS。
export async function zoteroSaveStandaloneAttachment(base, sessionID, title, buf) {
  const meta = JSON.stringify({ sessionID, title, url: '' });
  const r = await fetch(base + '/connector/saveStandaloneAttachment?sessionID=' + encodeURIComponent(sessionID),
    { method: 'POST', headers: { ...ZH, 'Content-Type': 'application/pdf', 'X-Metadata': meta }, body: buf });
  const body = (await r.text()).slice(0, 300);
  let canRecognize = false;
  try { canRecognize = JSON.parse(body).canRecognize === true; } catch { /* 非 JSON 忽略 */ }
  return { status: r.status, body, canRecognize };
}

export async function zoteroRecognizedItem(base, sessionID) {
  return zoteroPost(base, '/connector/getRecognizedItem', { sessionID });
}

// 分类树（id 形如 C33 / L1，即 updateSession 的 target），可选按名字反查
export async function zoteroTargets(base) {
  const r = await zoteroPost(base, '/connector/getSelectedCollection', {});
  if (r.status !== 200) return [];
  try { return JSON.parse(r.body).targets || []; } catch { return []; }
}
export function resolveTarget(targets, want) {
  const t = (want || '').trim();
  if (!t) return null;
  if (/^[CL]\d+$/i.test(t)) return t.toUpperCase();
  const hit = targets.find(x => x.name === t) || targets.find(x => String(x.name).toLowerCase() === t.toLowerCase());
  return hit ? hit.id : null;
}

// 库内已有附件的父条目 key 集合 —— 用来判断「这篇是不是已经有全文了」
export async function zoteroPdfParents(base) {
  const set = new Set();
  let start = 0;
  while (true) {
    let j;
    try { j = await fetchJson(`${base}/api/users/0/items?itemType=attachment&limit=100&start=${start}&format=json`, { tries: 5, pauseMs: 2000 }); }
    catch { break; }
    if (!Array.isArray(j) || !j.length) break;
    for (const it of j) if (/pdf/i.test((it.data || {}).contentType || '') && it.data.parentItem) set.add(it.data.parentItem);
    if (j.length < 100) break;
    start += 100;
  }
  return set;
}

// ---------- Crossref：DOI / 标题 -> final_items 形状 ----------
export function crossrefToFinal(it) {
  return {
    doi: normDoi(it.DOI),
    title: ((it.title && it.title[0]) || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim(),
    journal: ((it['container-title'] && it['container-title'][0]) || '').trim(),
    shortjournal: (it['short-container-title'] && it['short-container-title'][0]) || '',
    year: (it.issued?.['date-parts']?.[0]?.[0]) || '',
    month: (it.issued?.['date-parts']?.[0]?.[1]) || '',
    volume: it.volume || '', issue: it.issue || '', page: it.page || '',
    type: it.type || '', publisher: it.publisher || '',
    abstract: ((it.abstract || '').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()),
    authors: (it.author || []).map(a => ({ family: a.family || '', given: a.given || '' }))
  };
}
export async function crossrefByDoi(doi, mailto) {
  const j = await fetchJson(`https://api.crossref.org/works/${encodeURIComponent(doi)}?select=${encodeURIComponent(CROSSREF_SELECT)}&mailto=${encodeURIComponent(mailto || '')}`,
    { tries: 3, pauseMs: 1200, headers: { 'User-Agent': `lit-workflow/1.0 (mailto:${mailto || 'user@example.com'})` } });
  return j?.message && crossrefToFinal(j.message);
}
export async function crossrefByTitle(title, mailto, rows = 3) {
  if (!title || title.length < 12) return null;
  const j = await fetchJson(`https://api.crossref.org/works?query.bibliographic=${encodeURIComponent(title)}&rows=${rows}&select=${encodeURIComponent(CROSSREF_SELECT)}&mailto=${encodeURIComponent(mailto || '')}`,
    { tries: 3, pauseMs: 1200, headers: { 'User-Agent': `lit-workflow/1.0 (mailto:${mailto || 'user@example.com'})` } });
  const items = j?.message?.items || [];
  for (const it of items) {
    const f = crossrefToFinal(it);
    if (f.doi && titleSim(f.title, title, { minInter: 5, threshold: 0.75 })) return f;   // 标题够像才认
  }
  return null;
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
