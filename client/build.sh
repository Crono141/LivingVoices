#!/usr/bin/env bash
# Build LivingVoices.dll (32-bit, like Wow.exe) with the MinGW-w64 cross compiler (pacman: mingw-w64-gcc), and the
# Linux tools that write and check the pack's MPQ (mkpack, test_pack).
set -euo pipefail
cd "$(dirname "$0")"; mkdir -p build
# StormLib (third_party/StormLib, v9.40) as static libraries: 32-bit Windows for the DLL, native for the tools
if [[ ! -f build/storm-w32/libStormLib.a ]]; then
    cmake -S third_party/StormLib -B build/storm-w32 -DCMAKE_TOOLCHAIN_FILE="$PWD/third_party/mingw32.cmake" \
        -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF -DSTORM_SKIP_INSTALL=ON \
        -DCMAKE_C_FLAGS=-mstackrealign -DCMAKE_CXX_FLAGS=-mstackrealign >/dev/null
    cmake --build build/storm-w32 -j16 >/dev/null
fi
if [[ ! -f build/storm-native/libstorm.a ]]; then
    cmake -S third_party/StormLib -B build/storm-native -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
        -DSTORM_SKIP_INSTALL=ON >/dev/null
    cmake --build build/storm-native -j16 >/dev/null
fi
i686-w64-mingw32-g++ -std=c++17 -O2 -shared -mstackrealign -fno-exceptions -fno-rtti -Wall -Wno-unused-function \
    -static -static-libgcc -static-libstdc++ \
    -o build/LivingVoices.dll LivingVoices.cpp build/storm-w32/libStormLib.a -lole32 -lwinmm -luser32 -lwininet
i686-w64-mingw32-strip build/LivingVoices.dll
ls -la build/LivingVoices.dll
# the Wow.exe patcher for players without Python (the same bytes as patch_wowexe.py; patch_bytes.h)
i686-w64-mingw32-g++ -std=c++17 -O2 -Wall -static -static-libgcc -static-libstdc++ \
    -o build/LivingVoicesPatcher.exe LivingVoicesPatcher.cpp -ladvapi32
i686-w64-mingw32-strip build/LivingVoicesPatcher.exe
ls -la build/LivingVoicesPatcher.exe
# Linux: write the MPQ (build_release.py runs it) and read every line back through the DLL's own reader
g++ -std=c++17 -O2 -Wall -o build/mkpack mkpack.cpp build/storm-native/libstorm.a -lz -lbz2
g++ -std=c++17 -O2 -Wall -Wno-unused-function -o build/test_pack test_pack.cpp build/storm-native/libstorm.a -lz -lbz2 -lpthread -lm -ldl
