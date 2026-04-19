---
name: file-organizer
description: Categorize and suggest organization for files in a directory
version: "1.0"
triggers:
  - organize files
  - sort files
  - 파일 정리
  - 폴더 정리
tools: []
---

## Instructions

When the user asks to organize files in a directory, analyze the contents and
propose a clear organizational structure. Follow these steps:

1. **Scan the directory** — List all files and subdirectories. For each file,
   note:
   - File name and extension
   - File size
   - Last modified date
   - Current location (nested path)

2. **Categorize files** — Group files by type and purpose:

   | Category | Extensions / Patterns |
   |----------|-----------------------|
   | Documents | .pdf, .docx, .txt, .md, .pages |
   | Spreadsheets | .csv, .xlsx, .numbers |
   | Images | .png, .jpg, .jpeg, .gif, .svg, .webp |
   | Videos | .mp4, .mov, .avi, .mkv |
   | Audio | .mp3, .wav, .m4a, .flac |
   | Code | .py, .js, .ts, .go, .rs, .java, .html, .css |
   | Archives | .zip, .tar, .gz, .rar, .7z |
   | Config | .json, .yaml, .yml, .toml, .env, .ini |
   | Data | .db, .sqlite, .sql, .parquet |
   | Design | .fig, .sketch, .psd, .ai, .pen |
   | Other | everything else |

3. **Identify patterns** — Look for:
   - Date-based naming conventions (2024-01-15_report.pdf)
   - Project-based groupings (projectX_spec.md, projectX_design.fig)
   - Version suffixes (report_v2.pdf, report_final.pdf, report_FINAL_v3.pdf)
   - Duplicates or near-duplicates
   - Temporary or junk files (.DS_Store, thumbs.db, ~$*.docx)

4. **Propose a structure** — Suggest a reorganized directory tree:

```
<target_directory>/
├── documents/
│   ├── reports/
│   └── notes/
├── images/
│   ├── screenshots/
│   └── assets/
├── code/
│   ├── scripts/
│   └── configs/
├── data/
├── archive/
│   └── <old or versioned files>
└── _cleanup/
    └── <duplicates and junk files to review before deleting>
```

   Adapt the structure to what actually exists. Do not create empty categories.

5. **Generate the plan** — Present as a table:

   | Current Path | Proposed Path | Reason |
   |-------------|---------------|--------|
   | ./report_v2.pdf | ./documents/reports/report_v2.pdf | Document grouping |
   | ./IMG_2024.png | ./images/screenshots/IMG_2024.png | Image by type |
   | ./report_final_FINAL.pdf | ./_cleanup/report_final_FINAL.pdf | Likely duplicate |

6. **Safety rules**:
   - NEVER move or delete files without explicit user confirmation.
   - Always put questionable files in `_cleanup/` for manual review.
   - Preserve original file names unless the user asks for renaming.
   - Flag any files that look like they contain secrets (.env, credentials.*,
     *.pem, *.key) and warn before moving them.

7. **Execution** — After the user approves the plan:
   - Create the directory structure first.
   - Move files one category at a time.
   - Report results after each batch.
   - Verify no files were lost (compare counts before and after).

8. **Language** — Use the same language as the user's request. Korean requests
   get Korean explanations and category names.
