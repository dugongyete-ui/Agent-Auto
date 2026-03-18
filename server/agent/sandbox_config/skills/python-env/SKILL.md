---
name: python-env
description: Python environment information for this sandbox. Use when installing Python packages, checking what's available, or setting up Python scripts. Read this BEFORE attempting any pip install to avoid errors.
---

# Python Environment

## Pre-Installed Packages

These packages are already installed. DO NOT install them again:

```
requests, httpx, aiohttp
pandas, numpy, scipy
matplotlib, Pillow
beautifulsoup4, lxml
reportlab, python-docx, openpyxl
PyPDF2, pdfplumber, fpdf2
yt-dlp
flask, fastapi, uvicorn, pydantic
qrcode, Pygments, rich, colorama
python-dateutil, pytz, tzdata
playwright, selenium
tabulate, tqdm, Markdown, mistune
```

System tools available: `ffmpeg`, `imagemagick`, `curl`, `wget`, `jq`, `zip`, `unzip`

## Installing Additional Packages

**ALWAYS** use this exact format:
```bash
pip install --break-system-packages <package1> <package2>
```

**NEVER** use:
```bash
pip install -r requirements.txt  # WRONG: file may not exist
pip install <package>             # WRONG: missing --break-system-packages flag
```

## File Persistence Warning

This sandbox resets between sessions. Files written in a previous session do NOT exist now. Always create files fresh using `file_write` before referencing them.

## Standard Directories

| Path | Purpose |
|------|---------|
| `/home/ubuntu/` | Main workspace |
| `/home/ubuntu/output/` | Files to deliver to user |
| `/home/ubuntu/skills/` | Skill packages |
| `/home/ubuntu/Downloads/` | Downloaded files |
| `/home/ubuntu/upload/` | User-uploaded files |
