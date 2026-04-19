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
        # Get provider for analysis
        from birkin.gateway.deps import get_provider_router

        router_obj = get_provider_router()
        provider = router_obj.select()

        wiki = get_wiki_memory()
        compiler = ProfileCompiler(provider, wiki)

        # Run in thread pool to not block event loop (provider.complete is sync)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: compiler.compile_profile(conversations, on_progress=on_progress),
        )

        job.pages_created = result.pages_created
        job.errors = result.errors
        job.status = ImportStatus.DONE
        logger.info("Import job %s completed: %d pages", job_id, len(result.pages_created))

    except Exception as exc:
        job.status = ImportStatus.ERROR
        job.errors.append(f"Import failed: {exc!s}")
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
    """Read the compiled user profile from wiki pages."""
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
    }

    # Read each profile page
    user_page = wiki.get_page("entities", "user-profile")
    if user_page:
        profile["exists"] = True
        profile["job_role"] = _extract_field(user_page, "Role")
        profile["key_people"] = _extract_list(user_page, "Key People")

    expertise = wiki.get_page("concepts", "user-expertise")
    if expertise:
        profile["exists"] = True
        profile["expertise_areas"] = _extract_bullets(expertise)

    interests = wiki.get_page("concepts", "user-interests")
    if interests:
        profile["exists"] = True
        profile["interests"] = _extract_bullets(interests)

    projects = wiki.get_page("concepts", "user-projects")
    if projects:
        profile["exists"] = True
        profile["active_projects"] = _extract_bullets(projects)

    patterns = wiki.get_page("concepts", "user-patterns")
    if patterns:
        profile["exists"] = True
        profile["decision_patterns"] = _extract_bullets(patterns)

    style = wiki.get_page("concepts", "user-style")
    if style:
        profile["exists"] = True
        profile["tools_and_tech"] = _extract_list(style, "Tools & Technologies")
        # Communication style is the first non-header paragraph
        for line in style.split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("-") and not line.startswith("---"):
                profile["communication_style"] = line
                break

    return profile


@router.delete("")
async def delete_profile() -> dict[str, str]:
    """Delete all user profile wiki pages (reset)."""
    wiki = get_wiki_memory()
    slugs = [
        ("entities", "user-profile"),
        ("concepts", "user-expertise"),
        ("concepts", "user-interests"),
        ("concepts", "user-projects"),
        ("concepts", "user-patterns"),
        ("concepts", "user-style"),
    ]
    deleted = 0
    for category, slug in slugs:
        if wiki.delete_page(category, slug):
            deleted += 1

    return {"status": "ok", "pages_deleted": str(deleted)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
