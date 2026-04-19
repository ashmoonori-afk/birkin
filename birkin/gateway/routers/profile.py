"""Profile API — conversation import, profile read, and profile management."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from birkin.gateway.deps import get_wiki_memory
from birkin.memory.import_job import ImportJobManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/profile", tags=["profile"])

# ---------------------------------------------------------------------------
# Import Job Manager singleton
# ---------------------------------------------------------------------------

_import_manager: ImportJobManager | None = None


def _get_import_manager() -> ImportJobManager:
    global _import_manager  # noqa: PLW0603
    if _import_manager is None:
        _import_manager = ImportJobManager()
    return _import_manager


def reset_import_manager() -> None:
    global _import_manager  # noqa: PLW0603
    _import_manager = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/import")
async def import_conversations(file: UploadFile = File(...)) -> dict[str, Any]:
    """Upload a ChatGPT or Claude export JSON and start background analysis."""
    if not file.filename or not file.filename.endswith(".json"):
        raise HTTPException(400, "Only .json files are supported")

    manager = _get_import_manager()

    try:
        job = manager.create_job()
    except ValueError as exc:
        raise HTTPException(409, str(exc))

    # Read file
    try:
        raw = await file.read()
        if len(raw) > 200 * 1024 * 1024:  # 200MB limit
            job.status = __import__("birkin.memory.import_job", fromlist=["ImportStatus"]).ImportStatus.ERROR
            job.errors.append("File too large (max 200MB)")
            raise HTTPException(413, "File too large (max 200MB)")

        data = json.loads(raw)
    except json.JSONDecodeError:
        from birkin.memory.import_job import ImportStatus

        job.status = ImportStatus.ERROR
        job.errors.append("Invalid JSON file")
        raise HTTPException(400, "Invalid JSON file")

    # Parse conversations
    from birkin.memory.import_job import ImportStatus
    from birkin.memory.importers.base import auto_detect_and_parse

    job.status = ImportStatus.PARSING
    try:
        conversations = auto_detect_and_parse(data)
    except ValueError as exc:
        job.status = ImportStatus.ERROR
        job.errors.append(str(exc))
        raise HTTPException(400, str(exc))

    job.conversations_found = len(conversations)
    if conversations:
        job.source_format = conversations[0].source

    # Start background analysis
    asyncio.create_task(_run_import(job.id, conversations))

    return {
        "job_id": job.id,
        "status": "started",
        "conversations_found": len(conversations),
        "source_format": job.source_format,
    }


async def _run_import(job_id: str, conversations: list) -> None:
    """Background task: run ProfileCompiler and update job status."""
    from birkin.memory.import_job import ImportStatus
    from birkin.memory.profile_compiler import ProfileCompiler, ProgressInfo

    manager = _get_import_manager()
    job = manager.get_job(job_id)
    if not job:
        return

    job.status = ImportStatus.ANALYZING

    def on_progress(info: ProgressInfo) -> None:
        job.progress_phase = info.phase
        job.progress_current = info.current
        job.progress_total = info.total

    try:
        # Get provider for analysis — try each candidate until one works
        from birkin.gateway.deps import get_provider_router

        router_obj = get_provider_router()
        wiki = get_wiki_memory()

        provider = None
        for candidate in router_obj.select_with_fallback(max_fallbacks=5):
            try:
                from birkin.core.models import Message as Msg

                test_resp = candidate.complete([Msg(role="user", content="Reply OK")])
                if test_resp and test_resp.content:
                    provider = candidate
                    logger.info("Profile import using provider: %s/%s", candidate.name, candidate.model)
                    break
            except Exception as probe_exc:
                logger.debug("Provider %s probe failed: %s", candidate.name, probe_exc)
                continue

        if provider is None:
            # No LLM provider — use stats-based fallback
            logger.warning("No LLM provider available, using stats-based profile")
            result = _compile_stats_fallback(conversations, wiki)
            job.pages_created = result.pages_created
            job.errors = result.errors
            job.status = ImportStatus.DONE
            logger.info("Import job %s (stats fallback): %d pages", job_id, len(result.pages_created))
            return

        compiler = ProfileCompiler(provider, wiki)

        # Run in thread pool to not block event loop (provider.complete is sync)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: compiler.compile_profile(conversations, on_progress=on_progress),
        )

        # If LLM analysis failed entirely, fall back to stats
        if not result.pages_created and result.batches_failed > 0:
            logger.warning("LLM analysis failed, falling back to stats: %s", result.errors)
            result = _compile_stats_fallback(conversations, wiki)

        job.pages_created = result.pages_created
        job.errors = result.errors
        job.status = ImportStatus.DONE
        logger.info("Import job %s completed: %d pages", job_id, len(result.pages_created))

    except Exception as exc:
        # Last resort: try stats fallback even on unexpected errors
        try:
            wiki = get_wiki_memory()
            result = _compile_stats_fallback(conversations, wiki)
            job.pages_created = result.pages_created
            job.errors = [f"LLM failed ({exc!s}), used stats fallback."] + result.errors
            job.status = ImportStatus.DONE
            logger.warning("Import job %s LLM failed, stats fallback used", job_id)
        except Exception as fb_exc:
            job.status = ImportStatus.ERROR
            job.errors.append(f"Import failed: {exc!s}, fallback also failed: {fb_exc!s}")
            logger.error("Import job %s failed: %s", job_id, exc)


@router.get("/import/{job_id}")
async def get_import_status(job_id: str) -> dict[str, Any]:
    """Get the status of an import job."""
    manager = _get_import_manager()
    job = manager.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job.to_dict()


@router.get("")
async def get_profile() -> dict[str, Any]:
    """Read the compiled user profile from wiki pages.

    Supports both legacy flat pages and granular graph pages.
    """
    wiki = get_wiki_memory()

    profile: dict[str, Any] = {
        "exists": False,
        "job_role": None,
        "expertise_areas": [],
        "interests": [],
        "active_projects": [],
        "decision_patterns": [],
        "communication_style": None,
        "tools_and_tech": [],
        "key_people": [],
        "graph_pages": 0,
    }

    # Hub page — always check first
    user_page = wiki.get_page("entities", "user-profile")
    if user_page:
        profile["exists"] = True
        profile["job_role"] = _extract_field(user_page, "Role")

    # Scan all profile-tagged pages for granular graph data
    all_pages = wiki.list_pages()
    profile_pages = []
    for p in all_pages:
        slug = p["slug"]
        if slug.startswith("project-"):
            title = _title_from_page(wiki, p["category"], slug)
            if title:
                profile["active_projects"].append(title)
            profile_pages.append(p)
        elif slug.startswith("tool-"):
            title = _title_from_page(wiki, p["category"], slug)
            if title:
                profile["tools_and_tech"].append(title)
            profile_pages.append(p)
        elif slug.startswith("skill-"):
            title = _title_from_page(wiki, p["category"], slug)
            if title:
                profile["expertise_areas"].append(title)
            profile_pages.append(p)
        elif slug.startswith("person-"):
            title = _title_from_page(wiki, p["category"], slug)
            if title:
                profile["key_people"].append(title)
            profile_pages.append(p)
        elif slug.startswith("interest-"):
            title = _title_from_page(wiki, p["category"], slug)
            if title:
                profile["interests"].append(title)
            profile_pages.append(p)

    if profile_pages:
        profile["exists"] = True
        profile["graph_pages"] = len(profile_pages)

    # Fallback: read legacy flat pages if granular pages not found
    if not profile["expertise_areas"]:
        page = wiki.get_page("concepts", "user-expertise")
        if page:
            profile["exists"] = True
            profile["expertise_areas"] = _extract_bullets(page)

    if not profile["interests"]:
        page = wiki.get_page("concepts", "user-interests")
        if page:
            profile["exists"] = True
            profile["interests"] = _extract_bullets(page)

    if not profile["active_projects"]:
        page = wiki.get_page("concepts", "user-projects")
        if page:
            profile["exists"] = True
            profile["active_projects"] = _extract_bullets(page)

    if not profile["key_people"] and user_page:
        profile["key_people"] = _extract_list(user_page, "Key People")

    # Decision patterns (always single page)
    patterns = wiki.get_page("concepts", "user-patterns")
    if patterns:
        profile["exists"] = True
        profile["decision_patterns"] = _extract_bullets(patterns)

    # Communication style
    style = wiki.get_page("concepts", "user-style")
    if style:
        profile["exists"] = True
        body = _strip_frontmatter(style)
        if not profile["tools_and_tech"]:
            profile["tools_and_tech"] = _extract_list(style, "Tools & Technologies")
        for line in body.split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("-"):
                profile["communication_style"] = line
                break

    return profile


@router.delete("")
async def delete_profile() -> dict[str, str]:
    """Delete all user profile wiki pages (reset) — flat + granular."""
    wiki = get_wiki_memory()
    deleted = 0

    # Delete all profile-tagged granular pages
    prefixes = ("project-", "tool-", "skill-", "person-", "interest-")
    for page in wiki.list_pages():
        if any(page["slug"].startswith(p) for p in prefixes):
            if wiki.delete_page(page["category"], page["slug"]):
                deleted += 1

    # Delete flat pages
    for category, slug in [
        ("entities", "user-profile"),
        ("concepts", "user-expertise"),
        ("concepts", "user-interests"),
        ("concepts", "user-projects"),
        ("concepts", "user-patterns"),
        ("concepts", "user-style"),
    ]:
        if wiki.delete_page(category, slug):
            deleted += 1

    return {"status": "ok", "pages_deleted": str(deleted)}


# ---------------------------------------------------------------------------
# Stats-based fallback (no LLM required)
# ---------------------------------------------------------------------------


def _compile_stats_fallback(conversations: list, wiki: Any) -> Any:
    """Build a basic profile from conversation statistics when no LLM is available."""
    from collections import Counter

    from birkin.memory.profile_compiler import ProfileCompileResult

    result = ProfileCompileResult()
    result.conversations_processed = len(conversations)

    all_words: Counter[str] = Counter()
    topics: list[str] = []
    total_msgs = 0

    for conv in conversations:
        total_msgs += len(conv.user_messages)
        topics.append(conv.title)
        for msg in conv.user_messages:
            words = [w.lower() for w in msg.content.split() if len(w) > 3]
            all_words.update(words)

    interests = [t for t in topics if t and t != "Untitled"][:15]

    stop = {
        "this",
        "that",
        "with",
        "from",
        "have",
        "what",
        "about",
        "when",
        "your",
        "they",
        "will",
        "been",
        "their",
        "more",
        "there",
        "which",
        "would",
        "could",
        "should",
    }
    keywords = [w for w, _ in all_words.most_common(50) if w not in stop][:15]

    pages: list[str] = []

    role_text = f"**Role:** (Imported from {len(conversations)} conversations, {total_msgs} messages)"
    parts = ["# User Profile\n", role_text + "\n"]
    wiki.ingest(
        "entities",
        "user-profile",
        "\n".join(parts),
        tags=["profile", "imported"],
        source="stats_fallback",
    )
    pages.append("entities/user-profile")

    if interests:
        parts = ["# User Interests\n"] + [f"- {t}" for t in interests]
        wiki.ingest(
            "concepts",
            "user-interests",
            "\n".join(parts),
            tags=["profile", "interests", "imported"],
            source="stats_fallback",
        )
        pages.append("concepts/user-interests")

    if keywords:
        parts = ["# User Expertise\n"] + [f"- {k}" for k in keywords]
        wiki.ingest(
            "concepts",
            "user-expertise",
            "\n".join(parts),
            tags=["profile", "expertise", "imported"],
            source="stats_fallback",
        )
        pages.append("concepts/user-expertise")

    result.pages_created = pages
    result.errors.append("No LLM provider — profile built from stats. Configure an API key for deeper analysis.")
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _title_from_page(wiki: Any, category: str, slug: str) -> str | None:
    """Extract the H1 title from a wiki page, stripping frontmatter."""
    content = wiki.get_page(category, slug)
    if not content:
        return None
    body = _strip_frontmatter(content)
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter (---...---) from wiki page content."""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return content


def _extract_field(content: str, field_name: str) -> str | None:
    """Extract a **Field:** value from markdown."""
    content = _strip_frontmatter(content)
    for line in content.split("\n"):
        if f"**{field_name}:**" in line:
            parts = line.split(f"**{field_name}:**", 1)
            if len(parts) > 1:
                return parts[1].strip()
    return None


def _extract_bullets(content: str) -> list[str]:
    """Extract bullet-point items from markdown (skips frontmatter tags line)."""
    content = _strip_frontmatter(content)
    items = []
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("- "):
            items.append(line[2:].strip())
    return items


def _extract_list(content: str, section_name: str) -> list[str]:
    """Extract a list from a named section."""
    content = _strip_frontmatter(content)
    in_section = False
    items = []
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## ") and section_name in stripped:
            in_section = True
            continue
        if stripped.startswith("## ") and in_section:
            break
        if in_section and stripped.startswith("- "):
            items.append(stripped[2:].strip())
    return items
