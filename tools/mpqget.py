"""Read files out of the client's MPQs through StormLib (.lib/libstorm.so; built from
github.com/ladislav-zezula/StormLib with -DSTORM_USE_BUNDLED_LIBRARIES=ON). The speech archives use MPQ wave
(ADPCM) compression, which pure-Python readers do not decode.

    from mpqget import MPQ;  data = MPQ('/path/speech-enUS.MPQ').read('Sound\\\\Creature\\\\Thorim\\\\x.wav')
"""
import ctypes, os
_lib = ctypes.CDLL(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.lib', 'libstorm.so'))
_H = ctypes.c_void_p
_lib.SFileOpenArchive.argtypes = [ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(_H)]
_lib.SFileOpenFileEx.argtypes = [_H, ctypes.c_char_p, ctypes.c_uint, ctypes.POINTER(_H)]
_lib.SFileGetFileSize.argtypes = [_H, ctypes.POINTER(ctypes.c_uint)]; _lib.SFileGetFileSize.restype = ctypes.c_uint
_lib.SFileReadFile.argtypes = [_H, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_uint), ctypes.c_void_p]
_lib.SFileCloseFile.argtypes = [_H]; _lib.SFileCloseArchive.argtypes = [_H]
STREAM_FLAG_READ_ONLY = 0x100

class MPQ:
    def __init__(self, path):
        self.h = _H()
        if not _lib.SFileOpenArchive(path.encode(), 0, STREAM_FLAG_READ_ONLY, ctypes.byref(self.h)):
            raise OSError(f'cannot open {path}')
    def read(self, name):
        fh = _H()
        if not _lib.SFileOpenFileEx(self.h, name.encode(), 0, ctypes.byref(fh)):
            raise FileNotFoundError(name)
        try:
            n = _lib.SFileGetFileSize(fh, None); buf = ctypes.create_string_buffer(n); got = ctypes.c_uint()
            if not _lib.SFileReadFile(fh, buf, n, ctypes.byref(got), None) and got.value != n:
                raise OSError(f'read failed: {name}')
            return buf.raw[:got.value]
        finally:
            _lib.SFileCloseFile(fh)
    def close(self): _lib.SFileCloseArchive(self.h)
