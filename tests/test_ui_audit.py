"""The development-tools audit and its accepted exceptions (synthetic reports)."""
import json
from pathlib import Path
import unittest

from scripts.check_ui_audit import judge

ROOT = Path(__file__).resolve().parents[1]


def report(*direct):
    """An `npm audit --json` report: each advisory on its package, and a tool that depends on it."""
    vulnerabilities = {}
    for name, package, vulnerable, severity in direct:
        vulnerabilities[package] = {'severity': severity, 'via': [
            {'url': f'https://github.com/advisories/{name}', 'name': package, 'range': vulnerable, 'severity': severity}]}
        vulnerabilities['tool-of-' + package] = {'severity': severity, 'via': [package]}
    return {'vulnerabilities': vulnerabilities}


GLOB = ('GHSA-aaaa-bbbb-cccc', 'synthetic-glob', '<=4.0.7', 'high')
ACCEPTED = [{'advisory': GLOB[0], 'package': GLOB[1]}]
no_fix = lambda package, vulnerable: False


class UiAuditTests(unittest.TestCase):
    def test_an_accepted_advisory_passes_while_its_package_has_no_fix(self):
        self.assertEqual(judge(report(GLOB), ACCEPTED, no_fix), [])
        self.assertEqual(judge(report(), [], no_fix), [])

    def test_any_other_advisory_fails(self):
        other = ('GHSA-dddd-eeee-ffff', 'synthetic-other', '<2.0.0', 'moderate')
        problems = judge(report(GLOB, other), ACCEPTED, no_fix)
        self.assertEqual(len(problems), 1)
        self.assertIn('GHSA-dddd-eeee-ffff', problems[0])
        self.assertEqual(len(judge(report(GLOB), [], no_fix)), 1)
        # Another package under the accepted advisory's name is no exception.
        self.assertEqual(len(judge(report(GLOB), [{'advisory': GLOB[0], 'package': 'something-else'}], no_fix)), 1)
        # Below the level the audit always had (moderate), nothing is asked.
        self.assertEqual(judge(report(('GHSA-gggg-hhhh-iiii', 'synthetic-low', '*', 'low')), [], no_fix), [])

    def test_an_exception_never_outlives_its_reason(self):
        asked = []
        fixed = lambda package, vulnerable: asked.append((package, vulnerable)) or True
        self.assertIn('fixed version', judge(report(GLOB), ACCEPTED, fixed)[0])  # Update, then remove it.
        self.assertEqual(asked, [('synthetic-glob', '<=4.0.7')])
        self.assertIn('no longer reported', judge(report(), ACCEPTED, no_fix)[0])  # Updated: remove it.

    def test_the_program_itself_is_still_audited_with_no_exception(self):
        workflow = (ROOT / '.github/workflows/checks.yml').read_text(encoding='utf-8')
        self.assertIn('npm audit --omit=dev --audit-level=moderate', workflow)
        self.assertIn('python scripts/check_ui_audit.py', workflow)
        for item in json.loads((ROOT / 'ui/audit-exceptions.json').read_text(encoding='utf-8')):
            self.assertEqual(set(item), {'advisory', 'package', 'accepted', 'reason'})


if __name__ == '__main__':
    unittest.main()
