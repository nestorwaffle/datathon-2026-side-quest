"""Best-effort metrics of this process only; never inspects another agent."""
import os
import time

def snapshot():
    result={"pid":os.getpid(),"cpu_seconds":time.process_time(),"resident_bytes":None}
    if os.name=="nt":
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_=[("cb",wintypes.DWORD),("PageFaultCount",wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in (
                "PeakWorkingSetSize","WorkingSetSize","QuotaPeakPagedPoolUsage","QuotaPagedPoolUsage",
                "QuotaPeakNonPagedPoolUsage","QuotaNonPagedPoolUsage","PagefileUsage","PeakPagefileUsage")]
        counters=Counters();counters.cb=ctypes.sizeof(counters)
        kernel=ctypes.WinDLL("kernel32");kernel.GetCurrentProcess.restype=wintypes.HANDLE
        psapi=ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
        if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(counters),counters.cb):
            result["resident_bytes"]=int(counters.WorkingSetSize)
    return result
