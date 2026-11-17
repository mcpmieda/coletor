"""Native operational domain/DPAPI proof from the assembled portable interpreter.

Only synthetic unittest fixtures are loaded; no native dialog, source login,
named device key or network request is made. Domain modules must be bundled.
"""
import argparse
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest


def worker(output, runtime):
    import coletor.frequency_runtime as frequency
    import coletor.protected_storage as protected
    if (sys.platform != 'win32' or Path(sys.executable).resolve() != runtime.resolve()
            or Path(frequency.__file__).resolve().parents[2] != runtime.parent
            or Path(protected.__file__).resolve().parents[2] != runtime.parent):
        raise RuntimeError('bundled-frequency-runtime-required')
    root = Path(__file__).resolve().parents[1]
    suite = unittest.defaultTestLoader.discover(str(root / 'tests'), pattern='test_frequency_runtime.py')
    result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    # Only what was measured here: the suite ran in the bundled interpreter (checked above), on
    # Windows, with its native DPAPI and instance-lock tests not skipped.
    report = {'test': 'portable_windows_frequency_v2', 'status': 'passed' if result.wasSuccessful() and not result.skipped else 'failed',
              'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'skips': len(result.skipped)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return 0 if report['status'] == 'passed' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    runtime, output = args.python.resolve(), args.output.resolve()
    if args.worker: return worker(output, runtime)
    completed = subprocess.run([str(runtime), '-I', str(Path(__file__).resolve()), '--python', str(runtime),
                               '--output', str(output), '--worker'], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=120, check=False)
    if completed.returncode != 0: raise RuntimeError('native-frequency-proof-failed')
    print(json.dumps({'status': 'passed', 'evidence': 'portable_windows_frequency_v2'}))
    return 0


if __name__ == '__main__': raise SystemExit(main())
