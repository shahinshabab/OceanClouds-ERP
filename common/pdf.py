# common/pdf.py
"""
HTML/CSS -> PDF with WeasyPrint.

Documents are ordinary Django templates. Static files (fonts, artwork) are
read straight from disk instead of over HTTP, so PDFs render the same on a
laptop, in tests and behind Nginx.
"""

import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.conf import settings
from django.contrib.staticfiles import finders
from django.template.loader import render_to_string

try:
    from weasyprint import HTML, default_url_fetcher
except ImportError:  # pragma: no cover - WeasyPrint is in requirements
    HTML = None
    default_url_fetcher = None


def _static_path(url):
    path = unquote(urlparse(url).path)
    static_url = settings.STATIC_URL
    if not path.startswith(static_url):
        return None

    relative = path[len(static_url):]
    found = finders.find(relative)
    if found:
        return Path(found)

    candidate = Path(settings.STATIC_ROOT or "") / relative
    if settings.STATIC_ROOT and candidate.is_file():
        return candidate
    return None


def local_url_fetcher(url, *args, **kwargs):
    local = _static_path(url)
    if local is not None:
        mime_type, _ = mimetypes.guess_type(str(local))
        return {
            "string": local.read_bytes(),
            "mime_type": mime_type or "application/octet-stream",
            "filename": local.name,
        }
    return default_url_fetcher(url, *args, **kwargs)


def pdf_available():
    return HTML is not None


def render_pdf(template_name, context, request=None):
    html = render_to_string(template_name, context, request=request)
    base_url = request.build_absolute_uri("/") if request is not None else "http://localhost/"
    return HTML(string=html, base_url=base_url, url_fetcher=local_url_fetcher).write_pdf()
