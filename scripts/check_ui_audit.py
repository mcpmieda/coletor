"""The interface's development tools audited (npm audit), with the exceptions the owner accepted.

What goes inside the program is audited apart, with no exception at all
(`npm audit --omit=dev`, in .github/workflows/checks.yml). This is the whole set, development tools
included (vite, vitest, eslint), where an advisory with no fixed version published would otherwise
stop every Release for as long as its package takes to fix it.

An exception (ui/audit-exceptions.json) names one advisory of one package. It never outlives its
reason: the check fails again when the advisory is no longer reported (remove the exception) and
when the package publishes a version outside the vulnerable range (update it, then remove it).
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

SEVERITIES = ('info', 'low', 'moderate', 'high', 'critical')
THRESHOLD = 'moderate'  # As `npm audit --audit-level=moderate`.


def advisories(audit):
    """{advisory id: {'package', 'range', 'severity'}} of an `npm audit --json` report."""
    found = {}
    for entry in audit.get('vulnerabilities', {}).values():
        for via in entry.get('via', []):
            if isinstance(via, dict) and isinstance(via.get('url'), str):
                found[via['url'].rstrip('/').rsplit('/', 1)[-1]] = {
                    'package': via.get('name'), 'range': via.get('range'), 'severity': via.get('severity')}
    return found


def judge(audit, exceptions, fixed):
    """The problems to report (none: the audit passes).

    fixed(package, vulnerable_range): the package's latest published version is outside that range."""
    reported, problems = advisories(audit), []
    accepted = {item['advisory']: item for item in exceptions}
    for name, advisory in sorted(reported.items()):
        serious = SEVERITIES.index(advisory['severity']) >= SEVERITIES.index(THRESHOLD) if advisory['severity'] in SEVERITIES else True
        if not serious: continue
        exception = accepted.get(name)
        if exception is None:
            problems.append(f"{name} ({advisory['package']} {advisory['range']}, {advisory['severity']}): no exception")
        elif exception.get('package') != advisory['package']:
            problems.append(f"{name}: the exception names {exception.get('package')}, the advisory {advisory['package']}")
        elif fixed(advisory['package'], advisory['range']):
            problems.append(f"{name}: {advisory['package']} has a fixed version now; update it and remove the exception")
    for name in sorted(set(accepted) - set(reported)):
        problems.append(f"{name}: no longer reported; remove the exception")
    return problems


def run(command, folder):
    return subprocess.run(command, cwd=folder, capture_output=True, text=True, encoding='utf-8', timeout=300, check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ui', type=Path, default=Path(__file__).resolve().parents[1] / 'ui')
    args = parser.parse_args()
    npm, node = shutil.which('npm'), shutil.which('node')
    if not npm or not node: raise SystemExit('npm and node are required')
    audit = json.loads(run([npm, 'audit', '--json'], args.ui).stdout)
    if 'vulnerabilities' not in audit: raise SystemExit('npm audit gave no report')
    exceptions = json.loads((args.ui / 'audit-exceptions.json').read_text(encoding='utf-8'))

    def fixed(package, vulnerable):
        latest = run([npm, 'view', package, 'version'], args.ui).stdout.strip()
        if not latest: raise SystemExit(f'latest version of {package} unavailable')
        outside = run([node, '-e', 'process.exit(require("semver").satisfies(process.argv[1], process.argv[2]) ? 1 : 0)',
                       latest, vulnerable], args.ui)
        return outside.returncode == 0

    problems = judge(audit, exceptions, fixed)
    for problem in problems: print('audit:', problem, file=sys.stderr)
    if problems: raise SystemExit(1)
    print('ui-audit-passed:', len(exceptions), 'accepted exception(s)')


if __name__ == '__main__':
    main()
