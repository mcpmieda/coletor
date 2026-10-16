"""Read-only Windows Restart Manager query of a QA-owned temporary path."""
import ctypes
from ctypes import wintypes as w
from pathlib import Path


def locks(path):
    if not path:
        return {'resource_kind': 'unknown'}
    path = Path(path)
    files = [path] if path.is_file() else [p for p in path.rglob('*') if p.is_file()][:200]
    class Unique(ctypes.Structure):
        _fields_ = [('pid', w.DWORD), ('started', w.FILETIME)]
    class Process(ctypes.Structure):
        _fields_ = [('process', Unique), ('application', w.WCHAR * 256), ('service', w.WCHAR * 64),
                    ('type', ctypes.c_int), ('status', w.ULONG), ('session', w.DWORD), ('restartable', w.BOOL)]
    rm = ctypes.WinDLL('rstrtmgr')
    session, key = w.DWORD(), ctypes.create_unicode_buffer(33)
    result = {'resource_kind': 'directory' if path.is_dir() else 'file', 'suffix': path.suffix,
              'files_queried': len(files)}
    code = rm.RmStartSession(ctypes.byref(session), 0, key)
    if code:
        return {**result, 'query_error': code}
    try:
        names = (w.LPCWSTR * len(files))(*map(str, files))
        code = rm.RmRegisterResources(session, len(files), names, 0, None, 0, None)
        if code:
            return {**result, 'query_error': code}
        needed, count, reason = w.UINT(), w.UINT(), w.DWORD()
        code = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reason))
        if code not in (0, 234):
            return {**result, 'query_error': code}
        count.value = needed.value
        processes = (Process * needed.value)()
        code = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), processes, ctypes.byref(reason))
        result['query_error'] = code
        result['lockers'] = [{'pid': item.process.pid, 'application': item.application,
                              'service': item.service} for item in processes[:count.value]] if code == 0 else []
        return result
    finally:
        rm.RmEndSession(session)
