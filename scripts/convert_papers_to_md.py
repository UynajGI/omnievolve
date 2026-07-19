#!/usr/bin/env python3
"""Convert academic PDFs to Markdown with structure preservation."""

import sys, re, json
from pathlib import Path
import fitz  # PyMuPDF


def pdf_to_markdown(pdf_path: str) -> str:
    doc = fitz.open(pdf_path)
    lines = []
    for page in doc:
        blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_PRESERVE_WHITESPACE)["blocks"]
        for block in blocks:
            if block["type"] != 0:  # skip images
                continue
            spans = []
            for line in block["lines"]:
                for span in line["spans"]:
                    spans.append({
                        "text": span["text"].strip(),
                        "size": span["size"],
                        "flags": span["flags"],
                        "font": span["font"],
                    })
            if not spans:
                continue

            # Determine if heading based on font size (relative to page)
            avg_size = sum(s["size"] for s in spans) / len(spans)
            text = " ".join(s["text"] for s in spans)
            text = re.sub(r'\s+', ' ', text).strip()
            if not text:
                continue

            # Simple heuristic: larger font = heading
            page_w = page.rect.width
            is_large = avg_size > 11
            is_bold = any(s["flags"] & 2**4 for s in spans)  # bold bit

            if is_large and is_bold and len(text) < 200:
                if avg_size > 15:
                    lines.append(f"\n# {text}\n")
                elif avg_size > 13:
                    lines.append(f"\n## {text}\n")
                else:
                    lines.append(f"\n### {text}\n")
            elif re.match(r'^(Abstract|Introduction|Related Work|Method|Experiment|Conclusion|Appendix|References|Acknowledgments)', text, re.I):
                lines.append(f"\n## {text}\n")
            else:
                lines.append(text + "\n\n")

    doc.close()
    md = "".join(lines)
    # Clean up excessive blank lines
    md = re.sub(r'\n{3,}', '\n\n', md)
    return md.strip()


def main():
    papers_dir = Path("/home/jiangyuan/omnievolve/references/papers")
    out_dir = papers_dir / "md"
    out_dir.mkdir(exist_ok=True)

    for pdf in sorted(papers_dir.glob("*.pdf")):
        name = pdf.stem
        out_file = out_dir / f"{name}.md"
        if out_file.exists():
            print(f"  SKIP {name} (already exists)")
            continue
        print(f"  CONV {name} ...", end=" ", flush=True)
        try:
            md = pdf_to_markdown(str(pdf))
            out_file.write_text(md, encoding="utf-8")
            print(f"OK ({len(md)} chars)")
        except Exception as e:
            print(f"FAIL: {e}")


if __name__ == "__main__":
    main()
