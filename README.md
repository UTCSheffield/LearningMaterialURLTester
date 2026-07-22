# LearningMaterialURLTester

Look through folders of Learning Materials, extract URLs from:

- Markdown files (`.md`, `.markdown`)
- Word documents (`.docx`, `.docm`)
- PowerPoint files (`.pptx`, `.pptm`)

Then check each URL and report whether it appears to be blocked by Senso.

## Install

```bash
pip install .
```

## Run as a module

```bash
python -m learning_material_url_tester /path/to/learning-materials
```

This writes `url_check_results.csv` in the current directory by default.
