# PDFtoJPG

A small Python tool that converts PDF files to JPG images — one image per page.

## Install

```bash
pip install PyMuPDF Pillow
```

## Usage

Run with no arguments to open a file-picker dialog:

```bash
python PDFtoJPG.py
```

Or pass a PDF directly:

```bash
python PDFtoJPG.py document.pdf
```

Options:

```bash
python PDFtoJPG.py document.pdf -o output/ -d 300 -q 95
python PDFtoJPG.py document.pdf --pages 1-5
python PDFtoJPG.py document.pdf --password secret
python PDFtoJPG.py ./pdfs/ --recursive
```

| Flag              | Description                        | Default |
|-------------------|------------------------------------|---------|
| `-o`, `--output`  | Output directory                   | `<name>_images/` next to the PDF |
| `-d`, `--dpi`     | Resolution (72–600)                | `200`   |
| `-q`, `--quality` | JPG quality (1–100)                | `90`    |
| `-p`, `--password`| Password for encrypted PDFs        | —       |
| `--pages`         | Page range, e.g. `1-5`             | all     |
| `--recursive`     | Recurse into subfolders            | off     |
| `--pick-output`   | Also open a picker for output dir  | off     |
