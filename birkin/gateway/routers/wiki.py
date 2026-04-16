"""Wiki memory endpoints (pages, search, graph, upload, auto-link, summarize)."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from birkin.gateway.deps import get_wiki_memory

router = APIRouter(prefix="/api", tags=["wiki"])


@router.get("/wiki/pages")
def wiki_list_pages() -> list[dict]:
    wiki = get_wiki_memory()
    return wiki.list_pages()


@router.get("/wiki/pages/{category}/{slug}")
def wiki_get_page(category: str, slug: str) -> dict:
    wiki = get_wiki_memory()
    content = wiki.get_page(category, slug)
    if content is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return {"category": category, "slug": slug, "content": content}


@router.put("/wiki/pages/{category}/{slug}")
def wiki_put_page(category: str, slug: str, body: dict) -> dict:
    wiki = get_wiki_memory()
    wiki.ingest(category, slug, body.get("content", ""))
    return {"status": "ok"}


@router.delete("/wiki/pages/{category}/{slug}", status_code=204)
def wiki_delete_page(category: str, slug: str) -> None:
    wiki = get_wiki_memory()
    wiki.delete_page(category, slug)


@router.get("/wiki/search")
def wiki_search(q: str = "") -> list[dict]:
    wiki = get_wiki_memory()
    return wiki.query(q) if q else []


@router.get("/wiki/lint")
def wiki_lint() -> dict:
    wiki = get_wiki_memory()
    return {"warnings": wiki.lint()}


@router.get("/wiki/graph")
def wiki_graph() -> dict:
    """Build node-link graph data from wiki pages."""
    import re

    wiki = get_wiki_memory()
    pages = wiki.list_pages()
    wikilink_re = re.compile(r"\[\[([^\]]+)\]\]")

    nodes = []
    edges = []
    all_slugs = set()
    referenced = set()

    for p in pages:
        slug = p["slug"]
        cat = p["category"]
        all_slugs.add(slug)
        nodes.append({"slug": slug, "category": cat})

        content = wiki.get_page(cat, slug) or ""
        for m in wikilink_re.finditer(content):
            target = m.group(1).strip()
            referenced.add(target)
            edges.append({"source": slug, "target": target})

    orphans = list(all_slugs - referenced)
    # Add nodes for broken link targets
    for ref in referenced - all_slugs:
        nodes.append({"slug": ref, "category": "broken"})

    return {"nodes": nodes, "edges": edges, "orphans": orphans}


@router.post("/wiki/upload")
async def wiki_upload_file(file: UploadFile = File(...)) -> dict:
    """Upload a file (md, csv, xls/xlsx, txt, pdf) and ingest into wiki memory."""
    import csv
    import io
    import re

    wiki = get_wiki_memory()

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    raw = await file.read()
    content_bytes = raw
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""

    allowed_exts = {"md", "txt", "csv", "xls", "xlsx", "pdf"}
    if ext not in allowed_exts:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '.{ext}'. Allowed: {sorted(allowed_exts)}",
        )

    # Parse content based on extension
    if ext in ("md", "txt"):
        content = content_bytes.decode("utf-8", errors="replace")

    elif ext == "csv":
        text = content_bytes.decode("utf-8", errors="replace")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows:
            content = "(empty CSV)"
        else:
            # Build markdown table
            header = rows[0]
            lines = ["| " + " | ".join(header) + " |"]
            lines.append("| " + " | ".join("---" for _ in header) + " |")
            for row in rows[1:]:
                # Pad short rows
                padded = row + [""] * (len(header) - len(row))
                lines.append("| " + " | ".join(padded[: len(header)]) + " |")
            content = "\n".join(lines)

    elif ext in ("xlsx", "xls"):
        try:
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(content_bytes), read_only=True)
            sheets_content: list[str] = []
            for ws in wb.worksheets:
                rows = list(ws.iter_rows(values_only=True))
                if not rows:
                    continue
                header = [str(c) if c is not None else "" for c in rows[0]]
                lines = [f"## {ws.title}\n"]
                lines.append("| " + " | ".join(header) + " |")
                lines.append("| " + " | ".join("---" for _ in header) + " |")
                for row in rows[1:]:
                    cells = [str(c) if c is not None else "" for c in row]
                    padded = cells + [""] * (len(header) - len(cells))
                    lines.append("| " + " | ".join(padded[: len(header)]) + " |")
                sheets_content.append("\n".join(lines))
            wb.close()
            content = "\n\n".join(sheets_content) if sheets_content else "(empty spreadsheet)"
        except ImportError:
            content = "(Excel support requires openpyxl: pip install openpyxl)"
        except (ValueError, KeyError, IndexError, OSError) as exc:
            content = f"(Failed to parse Excel file: {exc})"

    elif ext == "pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content_bytes))
            pages_text = [page.extract_text() or "" for page in reader.pages]
            content = "\n\n---\n\n".join(pages_text).strip()
            if not content:
                content = "(PDF contained no extractable text)"
        except ImportError:
            content = "(PDF support requires pypdf: pip install pypdf)"
        except (ValueError, OSError) as exc:
            content = f"(Failed to parse PDF: {exc})"
    else:
        content = content_bytes.decode("utf-8", errors="replace")

    # Determine category
    name_lower = file.filename.lower()
    entity_hints = ["people", "team", "person", "contact", "employee", "org", "company", "member"]
    category = "entities" if any(h in name_lower for h in entity_hints) else "concepts"

    # Generate sanitized slug from filename
    stem = file.filename.rsplit(".", 1)[0] if "." in file.filename else file.filename
    slug = re.sub(r"[^a-zA-Z0-9_-]", "-", stem).strip("-").lower()
    slug = re.sub(r"-+", "-", slug)
    if not slug:
        slug = "uploaded-file"

    wiki.ingest(category, slug, content)

    preview = content[:300] + ("..." if len(content) > 300 else "")
    return {"status": "ok", "category": category, "slug": slug, "preview": preview}


@router.post("/wiki/auto-link")
def wiki_auto_link() -> dict:
    """Scan all pages and auto-insert [[wikilinks]] where page slugs appear in text."""
    wiki = get_wiki_memory()
    count = wiki.auto_link()
    return {"links_added": count}


@router.post("/wiki/summarize")
def wiki_summarize() -> dict:
    """Merge old session pages into date-grouped summaries."""
    wiki = get_wiki_memory()
    deleted = wiki.summarize_old_sessions(max_age_hours=24)
    return {"summarized": len(deleted), "deleted_slugs": deleted}
