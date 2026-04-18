from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

try:
    import fitz  
except ImportError:
    sys.stderr.write("Error: PyMuPDF not installed.  pip install PyMuPDF\n")
    sys.exit(1)

try:
    from PIL import Image
except ImportError:
    sys.stderr.write("Error: Pillow not installed.  pip install Pillow\n")
    sys.exit(1)


# --------------------
# Configuration
# --------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("pdf2jpg")

DEFAULT_DPI = 200
DEFAULT_QUALITY = 90
MIN_DPI, MAX_DPI = 72, 600
MIN_QUALITY, MAX_QUALITY = 1, 100
PDF_EXTENSIONS = {".pdf"}


class PDFConversionError(Exception):
    """Raised when a PDF cannot be converted."""


# ---------------------
# File picker (GUI)
# ---------------------

def pick_pdf_files() -> list[Path]:
    """Open a native file-picker dialog. Returns [] if the user cancels."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        logger.error("tkinter is not available in this Python install.")
        return []

    root = tk.Tk()
    root.withdraw()                    # hide the empty root window
    root.attributes("-topmost", True)  # bring dialog to front on all OSes

    selected = filedialog.askopenfilenames(
        title="Select PDF file(s) to convert",
        filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
    )
    root.destroy()
    return [Path(p) for p in selected]


def pick_output_dir(initial_dir: Path | None = None) -> Path | None:
    """Open a folder-picker. Returns None if the user cancels."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    selected = filedialog.askdirectory(
        title="Select output folder (Cancel = save next to PDF)",
        initialdir=str(initial_dir) if initial_dir else None,
        mustexist=False,
    )
    root.destroy()
    return Path(selected) if selected else None


# -------------------------------------
# Discovery (for CLI directory input)
# -------------------------------------

def find_pdfs(path: Path, recursive: bool = False) -> list[Path]:
    """Return a sorted list of PDF files at the given path."""
    if path.is_file():
        if path.suffix.lower() in PDF_EXTENSIONS:
            return [path]
        raise ValueError(f"Not a PDF file: {path}")

    if path.is_dir():
        pattern = "**/*.pdf" if recursive else "*.pdf"
        pdfs = sorted(p for p in path.glob(pattern) if p.is_file())
        if not pdfs:
            raise ValueError(f"No PDF files found in: {path}")
        return pdfs

    raise FileNotFoundError(f"Path does not exist: {path}")


# ---------------------------
# Core conversion
# ---------------------------

def convert_pdf_to_jpg(
    pdf_path: Path,
    output_dir: Path,
    dpi: int = DEFAULT_DPI,
    quality: int = DEFAULT_QUALITY,
    password: str | None = None,
    page_range: tuple[int, int] | None = None,
) -> list[Path]:
    """Convert a single PDF to JPG image(s), one per page."""
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    if not (MIN_DPI <= dpi <= MAX_DPI):
        raise ValueError(f"DPI must be in [{MIN_DPI}, {MAX_DPI}], got {dpi}")
    if not (MIN_QUALITY <= quality <= MAX_QUALITY):
        raise ValueError(f"Quality must be in [{MIN_QUALITY}, {MAX_QUALITY}], got {quality}")

    output_dir.mkdir(parents=True, exist_ok=True)

    doc = None
    generated: list[Path] = []

    try:
        try:
            doc = fitz.open(pdf_path)
        except Exception as exc:
            raise PDFConversionError(f"Could not open '{pdf_path.name}': {exc}") from exc

        if doc.is_encrypted:
            if password is None:
                raise PDFConversionError(
                    f"'{pdf_path.name}' is password-protected. Supply --password."
                )
            if not doc.authenticate(password):
                raise PDFConversionError(f"Incorrect password for '{pdf_path.name}'.")

        total_pages = doc.page_count
        if total_pages == 0:
            raise PDFConversionError(f"'{pdf_path.name}' has no pages.")

        if page_range is not None:
            start = max(1, page_range[0])
            end = min(total_pages, page_range[1])
            if start > end:
                raise ValueError(f"Invalid page range: {page_range}")
            page_indices = range(start - 1, end)
        else:
            page_indices = range(total_pages)

        zoom = dpi / 72.0  # PDF user-space is 72 DPI
        matrix = fitz.Matrix(zoom, zoom)
        pad = max(3, len(str(total_pages)))
        stem = pdf_path.stem

        logger.info(
            "Converting '%s' (%d page%s) at %d DPI ...",
            pdf_path.name,
            len(page_indices),
            "s" if len(page_indices) != 1 else "",
            dpi,
        )

        for page_idx in page_indices:
            try:
                page = doc.load_page(page_idx)
                # JPG can't store alpha or CMYK — flatten to RGB on white.
                pix = page.get_pixmap(
                    matrix=matrix,
                    alpha=False,
                    colorspace=fitz.csRGB,
                )

                out_name = f"{stem}_page_{page_idx + 1:0{pad}d}.jpg"
                out_path = output_dir / out_name

                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                img.save(
                    out_path,
                    format="JPEG",
                    quality=quality,
                    optimize=True,
                    progressive=True,
                )

                generated.append(out_path)
                logger.debug("  saved %s (%dx%d)", out_path.name, pix.width, pix.height)

            except Exception as exc:
                logger.error("  page %d failed: %s", page_idx + 1, exc)
                continue

        if not generated:
            raise PDFConversionError(f"No pages converted from '{pdf_path.name}'.")

        logger.info(
            "  %d JPG file%s written to %s",
            len(generated),
            "s" if len(generated) != 1 else "",
            output_dir,
        )
        return generated

    finally:
        if doc is not None:
            doc.close()


# -------------------------------
# CLI
# -------------------------------

def parse_page_range(value: str) -> tuple[int, int]:
    """Parse '1-5' or '3' into (start, end)."""
    value = value.strip()
    try:
        if "-" in value:
            a, b = value.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid page range: '{value}'")

    if start < 1 or end < 1:
        raise argparse.ArgumentTypeError("Page numbers must be >= 1")
    if start > end:
        raise argparse.ArgumentTypeError(f"Invalid range: start ({start}) > end ({end})")
    return start, end


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Convert PDF files to JPG images (one image per page). "
                    "Run with no input argument to open a file-picker dialog.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python pdf_to_jpg.py                         # file picker\n"
            "  python pdf_to_jpg.py document.pdf\n"
            "  python pdf_to_jpg.py document.pdf -o out/ -d 300 -q 95\n"
            "  python pdf_to_jpg.py document.pdf --pages 1-5\n"
            "  python pdf_to_jpg.py pdfs/ --recursive\n"
        ),
    )
    p.add_argument("input", type=Path, nargs="?", default=None,
                   help="PDF file or directory. Omit to open a file-picker.")
    p.add_argument("-o", "--output", type=Path, default=None,
                   help="Output directory (default: <stem>_images next to the PDF)")
    p.add_argument("-d", "--dpi", type=int, default=DEFAULT_DPI,
                   help=f"Resolution in DPI ({MIN_DPI}-{MAX_DPI}, default: {DEFAULT_DPI})")
    p.add_argument("-q", "--quality", type=int, default=DEFAULT_QUALITY,
                   help=f"JPG quality ({MIN_QUALITY}-{MAX_QUALITY}, default: {DEFAULT_QUALITY})")
    p.add_argument("-p", "--password", default=None,
                   help="Password for encrypted PDFs")
    p.add_argument("--pages", type=parse_page_range, default=None,
                   help="Page range, e.g. '1-5' or '3' (default: all)")
    p.add_argument("--recursive", action="store_true",
                   help="Recurse into subdirectories (when input is a directory)")
    p.add_argument("--no-picker", action="store_true",
                   help="Disable the GUI file-picker fallback.")
    p.add_argument("--pick-output", action="store_true",
                   help="Also open a folder-picker for the output directory.")
    p.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    return p


def _pause_if_interactive(picker_mode: bool) -> None:
    """Keep the console open when the user double-clicked the script."""
    if not picker_mode:
        return
    try:
        input("\nPress Enter to exit ...")
    except (EOFError, KeyboardInterrupt):
        pass


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    picker_mode = args.input is None and not args.no_picker

    # Resolve input
    try:
        if args.input is not None:
            pdfs = find_pdfs(args.input.expanduser().resolve(), args.recursive)
        elif picker_mode:
            logger.info("Opening file picker ...")
            picked = pick_pdf_files()
            if not picked:
                logger.info("No file selected. Exiting.")
                _pause_if_interactive(picker_mode)
                return 0
            pdfs = [p.expanduser().resolve() for p in picked]
        else:
            logger.error("No input provided and --no-picker is set.")
            return 1
    except (FileNotFoundError, ValueError) as exc:
        logger.error(str(exc))
        _pause_if_interactive(picker_mode)
        return 1

    # Resolve the output directory
    picked_output: Path | None = args.output
    if picked_output is None and args.pick_output:
        picked_output = pick_output_dir(initial_dir=pdfs[0].parent)

    # Convert
    success, failure = 0, 0
    for pdf_path in pdfs:
        if picked_output is not None:
            out_dir = picked_output.expanduser().resolve()
            if len(pdfs) > 1:
                out_dir = out_dir / pdf_path.stem
        else:
            out_dir = pdf_path.parent / f"{pdf_path.stem}_images"

        try:
            convert_pdf_to_jpg(
                pdf_path=pdf_path,
                output_dir=out_dir,
                dpi=args.dpi,
                quality=args.quality,
                password=args.password,
                page_range=args.pages,
            )
            success += 1
        except (PDFConversionError, FileNotFoundError, ValueError) as exc:
            logger.error("Failed: %s", exc)
            failure += 1
        except KeyboardInterrupt:
            logger.warning("Interrupted by user.")
            return 130

    if success + failure > 1:
        logger.info("Done: %d succeeded, %d failed.", success, failure)

    _pause_if_interactive(picker_mode)
    return 0 if failure == 0 else 2


if __name__ == "__main__":
    sys.exit(main())