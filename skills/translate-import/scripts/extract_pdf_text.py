# -*- coding: utf-8 -*-
"""Extract text blocks and raster images from a PDF for translation.

Usage:
    python extract_pdf_text.py <pdf_path> <image_dir> > extract.json

stdout: JSON {file, npages, total_chars, pages:[{page, blocks:[...], images:[...]}]}
Images (width/height >= 120 px) are saved as PNG into <image_dir>.
"""
import json, os, sys
import pymupdf

def main():
    pdf_path = sys.argv[1]
    image_dir = sys.argv[2] if len(sys.argv) > 2 else "pdf_images"
    os.makedirs(image_dir, exist_ok=True)

    doc = pymupdf.open(pdf_path)
    out = {"file": pdf_path, "npages": doc.page_count, "pages": []}
    total_chars = 0
    saved_names = {}

    for pno in range(doc.page_count):
        page = doc[pno]
        d = page.get_text("dict", sort=True)
        blocks = []
        for b in d["blocks"]:
            if b["type"] == 0:
                lines = []
                max_size = 0.0
                bold_chars = 0
                all_chars = 0
                for ln in b.get("lines", []):
                    lt = ""
                    for sp in ln.get("spans", []):
                        lt += sp["text"]
                        max_size = max(max_size, sp["size"])
                        all_chars += len(sp["text"].strip())
                        if sp["flags"] & 16:
                            bold_chars += len(sp["text"].strip())
                    lines.append(lt)
                text = "\n".join(lines)
                if not text.strip():
                    continue
                total_chars += len(text)
                blocks.append({
                    "kind": "text",
                    "text": text,
                    "size": round(max_size, 1),
                    "bold": all_chars > 0 and bold_chars >= all_chars * 0.5,
                    "bbox": [round(v, 1) for v in b["bbox"]],
                })
        images = []
        for i, im in enumerate(page.get_images(full=True)):
            xref = im[0]
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                rects = []
            if not rects:
                continue
            r = rects[0]
            if r.width < 60 or r.height < 60:
                continue
            name = saved_names.get(xref)
            if name is None:
                try:
                    pix = pymupdf.Pixmap(doc, xref)
                    if pix.colorspace and pix.colorspace.n > 3:
                        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                    if pix.width < 120 or pix.height < 120:
                        pix = None
                    else:
                        name = "p{:02d}_{:02d}.png".format(pno + 1, len(saved_names))
                        pix.save(os.path.join(image_dir, name))
                        saved_names[xref] = name
                    if pix is None:
                        continue
                except Exception:
                    continue
            images.append({"file": name, "bbox": [round(v, 1) for v in [r.x0, r.y0, r.x1, r.y1]]})
        out["pages"].append({"page": pno + 1, "blocks": blocks, "images": images})

    out["total_chars"] = total_chars
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print(file=sys.stdout)
    print("npages={} total_chars={} images_saved={}".format(
        out["npages"], total_chars, len(saved_names)), file=sys.stderr)

if __name__ == "__main__":
    main()
