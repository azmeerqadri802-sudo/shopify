"""Windows 11 Mica and Acrylic backdrop effects with graceful fallback."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


def apply_windows_backdrop(hwnd: int) -> str:
    if sys.platform != "win32":
        return "qt fallback"
    try:
        dwm = ctypes.WinDLL("dwmapi")
        backdrop = wintypes.DWORD(2)  # DWMSBT_MAINWINDOW (Mica)
        result = dwm.DwmSetWindowAttribute(
            wintypes.HWND(hwnd), 38, ctypes.byref(backdrop), ctypes.sizeof(backdrop)
        )
        dark = wintypes.BOOL(True)
        dwm.DwmSetWindowAttribute(
            wintypes.HWND(hwnd), 20, ctypes.byref(dark), ctypes.sizeof(dark)
        )
        if result == 0:
            return "mica"
    except Exception:
        pass
    try:
        class AccentPolicy(ctypes.Structure):
            _fields_ = [
                ("AccentState", ctypes.c_int),
                ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint),
                ("AnimationId", ctypes.c_int),
            ]

        class CompositionData(ctypes.Structure):
            _fields_ = [
                ("Attribute", ctypes.c_int),
                ("Data", ctypes.POINTER(AccentPolicy)),
                ("SizeOfData", ctypes.c_size_t),
            ]

        policy = AccentPolicy(4, 2, 0xCC10141D, 0)  # Acrylic blur
        data = CompositionData(19, ctypes.pointer(policy), ctypes.sizeof(policy))
        user32 = ctypes.WinDLL("user32")
        if user32.SetWindowCompositionAttribute(wintypes.HWND(hwnd), ctypes.byref(data)):
            return "acrylic"
    except Exception:
        pass
    return "qt fallback"

