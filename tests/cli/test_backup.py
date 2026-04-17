"""Tests for birkin export / import CLI backup module."""

from __future__ import annotations

import zipfile

import pytest

from birkin.cli.backup import export_archive, import_archive


def _seed_workspace(base):
    """Create a minimal workspace tree under *base*."""
    (base / "birkin_sessions.db").write_text("fake-db-content")
    (base / "birkin_config.json").write_text('{"key": "value"}')

    wiki = base / "memory" / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "index.md").write_text("# Wiki index")
    (wiki / "log.md").write_text("# Log")

    traces = base / "traces"
    traces.mkdir()
    (traces / "2024-01-01.jsonl").write_text('{"event": 1}\n')


class TestExportCreatesZip:
    def test_export_creates_zip(self, tmp_path):
        _seed_workspace(tmp_path)
        result = export_archive(base_dir=str(tmp_path))

        assert result.exists()
        assert result.suffix == ".zip"

        with zipfile.ZipFile(result, "r") as zf:
            names = set(zf.namelist())
            assert "birkin_sessions.db" in names
            assert "birkin_config.json" in names
            assert "memory/wiki/index.md" in names
            assert "memory/wiki/log.md" in names
            assert "traces/2024-01-01.jsonl" in names


class TestImportRestoresFiles:
    def test_import_restores_files(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        _seed_workspace(src)

        archive = export_archive(base_dir=str(src))

        dest = tmp_path / "dest"
        dest.mkdir()
        summary = import_archive(str(archive), target_dir=str(dest))

        assert summary["files_restored"] == 5
        assert summary["sessions_db"] is True
        assert summary["wiki_pages"] == 2
        assert summary["config"] is True

        assert (dest / "birkin_sessions.db").read_text() == "fake-db-content"
        assert (dest / "birkin_config.json").read_text() == '{"key": "value"}'
        assert (dest / "memory" / "wiki" / "index.md").read_text() == "# Wiki index"


class TestExportImportWithPassword:
    def test_round_trip_encrypted(self, tmp_path):
        cryptography = pytest.importorskip("cryptography")  # noqa: F841

        src = tmp_path / "src"
        src.mkdir()
        _seed_workspace(src)

        archive = export_archive(
            base_dir=str(src),
            password="s3cret",
        )
        assert archive.suffix == ".birkin"

        # Encrypted file should not be a valid zip
        with pytest.raises(zipfile.BadZipFile):
            zipfile.ZipFile(archive, "r")

        dest = tmp_path / "dest"
        dest.mkdir()
        summary = import_archive(str(archive), password="s3cret", target_dir=str(dest))

        assert summary["files_restored"] == 5
        assert (dest / "birkin_sessions.db").read_text() == "fake-db-content"


class TestImportWrongPassword:
    def test_wrong_password_raises(self, tmp_path):
        cryptography = pytest.importorskip("cryptography")  # noqa: F841

        src = tmp_path / "src"
        src.mkdir()
        _seed_workspace(src)

        archive = export_archive(base_dir=str(src), password="correct")

        with pytest.raises(ValueError, match="Wrong password"):
            import_archive(str(archive), password="wrong")


class TestExportEmpty:
    def test_empty_workspace_creates_valid_zip(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()

        archive = export_archive(base_dir=str(empty))
        assert archive.exists()
        assert archive.stat().st_size > 0

        with zipfile.ZipFile(archive, "r") as zf:
            assert zf.namelist() == []


class TestImportMissingArchive:
    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            import_archive(str(tmp_path / "nonexistent.zip"))


class TestImportEncryptedWithoutPassword:
    def test_missing_password_raises(self, tmp_path):
        cryptography = pytest.importorskip("cryptography")  # noqa: F841

        src = tmp_path / "src"
        src.mkdir()
        _seed_workspace(src)

        archive = export_archive(base_dir=str(src), password="secret")

        with pytest.raises(ValueError, match="password is required"):
            import_archive(str(archive))
