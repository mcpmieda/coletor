"""Versioned budgets shared with the UI; no diary input is read here."""
import json
from pathlib import Path

LIMITS = json.loads(Path(__file__).with_name('preview-limits.json').read_text(encoding='utf-8'))
MAX_HTML_BYTES = LIMITS['htmlBytes']
MAX_REQUEST_BYTES = LIMITS['requestBytes']
MAX_STUDENTS = LIMITS['students']
MAX_RECORDS = LIMITS['records']
MAX_ISSUES = LIMITS['issues']
MAX_NODES = LIMITS['nodes']
