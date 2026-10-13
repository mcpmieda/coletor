"""Measure dense synthetic grids only, never accept input diaries."""
import ctypes
from ctypes import wintypes
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from coletor.demo import build_fixture
from coletor.parser import parse_annual_html


def dense_cards(count):
    html = build_fixture(students=1, include_edge_cases=False)
    start, end = html.index('<div style="page-break-inside: avoid;"'), html.index('<footer')
    card = html[start:end]
    cards = ''.join(card.replace('data-student-row="1"',f'data-student-row="{i}"').replace('Aluno sintético 001',f'Aluno sintético {i:03d}') for i in range(1,count+1))
    return (html[:start]+cards+html[end:]).replace('data-student-count="1"',f'data-student-count="{count}"')


def peak_memory():
    if os.name != 'nt':
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    class Counters(ctypes.Structure):
        _fields_ = [('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)] + [(name,ctypes.c_size_t) for name in ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage','QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    counters = Counters(); counters.cb = ctypes.sizeof(counters)
    kernel = ctypes.WinDLL('kernel32'); kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL('psapi'); psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p,wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(counters),counters.cb): raise OSError('memory measurement failed')
    return counters.PeakWorkingSetSize


if __name__ == '__main__':
    if len(sys.argv) == 2:
        count = int(sys.argv[1]); html = dense_cards(count)
        started = time.perf_counter(); snapshot = parse_annual_html(html,'TESTE-A',2026)
        elapsed = time.perf_counter()-started
        result = {'cards':count,'html_bytes':len(html.encode()),'request_json_bytes':len(json.dumps({'html':html,'class_id':'TESTE-A','year':2026}).encode()),'records':len(snapshot.records),'seconds':round(elapsed,3),'snapshot_json_bytes':len(json.dumps(asdict(snapshot)).encode()),'peak_working_set_bytes':peak_memory(),'volume_blocked':any(i.code in {'REPORT_VOLUME_EXCEEDED','DOCUMENT_TOO_LARGE','DOCUMENT_MALFORMED'} for i in snapshot.issues)}
        print(json.dumps(result)); assert len(snapshot.students)==count and len(snapshot.records)==count*334*6
    else:
        for count in (32,40,50,64):
            subprocess.run([sys.executable,__file__,str(count)],check=True)
