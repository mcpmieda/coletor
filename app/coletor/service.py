"""The same in-memory preview service is used by native and browser adapters."""
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from .parser import parse_annual_html
from .validation import validate_for_transmission
from .demo import build_fixture

ROOT = Path(__file__).resolve().parents[2]
MAX_HTML_BYTES = 8 * 1024 * 1024


def preview(html: str, class_id: str, year: int, mode: str = "local") -> dict:
    if not isinstance(html, str) or len(html.encode("utf-8")) > MAX_HTML_BYTES:
        raise ValueError("Diário inválido ou acima de 8 MB.")
    if not isinstance(class_id, str) or not class_id.strip() or len(class_id) > 80:
        raise ValueError("Informe um identificador de turma válido.")
    if type(year) is not int or not 2000 <= year <= 2100:
        raise ValueError("Informe um ano entre 2000 e 2100.")
    snapshot = parse_annual_html(html, class_id.strip(), year)
    return {"snapshot": asdict(snapshot), "validation": asdict(validate_for_transmission(snapshot)),
            "mode": mode, "processed_at": datetime.now(timezone.utc).isoformat()}


class PreviewApi:
    """Only these two read-only methods are exposed to the native webview."""

    def load_demo(self):
        try:
            html = build_fixture()
            return preview(html, "TESTE-A", 2026, "demo")
        except (OSError, ValueError, RecursionError):
            return {"error": "Não foi possível abrir a demonstração."}

    def preview_html(self, html, class_id, year):
        try:
            return preview(html, class_id, year)
        except (ValueError, TypeError, RecursionError):
            return {"error": "Não foi possível ler o diário. Confira o HTML, a turma e o ano."}
