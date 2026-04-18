from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    sys.stderr.write("Error: PyMuPDF not installed.  pip install PyMuPDF\n")
    sys.exit(1)

try:
    from PIL import Image
except ImportError:
    sys.stderr.write("Error: Pillow not installed.  pip install Pillow\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Core conversion
# ---------------------------------------------------------------------------

def convert_pdf_to_jpg(
    pdf_path: Path,
    output_dir: Path,
    dpi: int = DEFAULT_DPI,
    quality: int = DEFAULT_QUALITY,
    password: str | None = None,
    page_range: tuple[int, int] | None = None,
) -> list[Path]:
    """
    Convert a single PDF to JPG image(s), one per page.

    Args:
        pdf_path:    Path to the PDF file.
        output_dir:  Directory to save JPGs (created if missing).
        dpi:         Render resolution. Higher = sharper + larger file.
        quality:     JPG compression quality (1-100).
        password:    Password for encrypted PDFs.
        page_range:  Optional (start, end) inclusive, 1-indexed. None = all.

    Returns:
        List of paths to the generated JPG files.
    """
    # --- Validation --------------------------------------------------------
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
        # --- Open PDF ------------------------------------------------------
        try:
            doc = fitz.open(pdf_path)
        except Exception as exc:
            raise PDFConversionError(f"Could not open '{pdf_path.name}': {exc}") from exc

        # --- Decrypt if needed --------------------------------------------
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

        # --- Resolve page range -------------------------------------------
        if page_range is not None:
            start = max(1, page_range[0])
            end = min(total_pages, page_range[1])
            if start > end:
                raise ValueError(f"Invalid page range: {page_range}")
            page_indices = range(start - 1, end)
        else:
            page_indices = range(total_pages)

        # --- Render settings ----------------------------------------------
        zoom = dpi / 72.0  
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

        # --- Render each page ---------------------------------------------
        for page_idx in page_indices:
            try:
                page = doc.load_page(page_idx)

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


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

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
        description="Convert PDF files to JPG images (one image per page).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python pdf_to_jpg.py document.pdf\n"
            "  python pdf_to_jpg.py document.pdf -o out/ -d 300 -q 95\n"
            "  python pdf_to_jpg.py document.pdf --pages 1-5\n"
            "  python pdf_to_jpg.py pdfs/ --recursive\n"
        ),
    )
    p.add_argument("input", type=Path, help="PDF file or directory containing PDFs")
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
    p.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    try:
        pdfs = find_pdfs(args.input.expanduser().resolve(), args.recursive)
    except (FileNotFoundError, ValueError) as exc:
        logger.error(str(exc))
        return 1

    success, failure = 0, 0

    for pdf_path in pdfs:
        if args.output is not None:
            out_dir = args.output.expanduser().resolve()
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

    return 0 if failure == 0 else 2


if __name__ == "__main__":
    sys.exit(main())