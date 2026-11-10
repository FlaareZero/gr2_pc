#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-or-later
# Original C runtime using the local toolchain and GPU library, no files overwritten.
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
ref=a2e69a1bc506865716cb4e16f2c50f047bf65e57
stock=out/ab-build/stock-src
mkdir -p "$stock"
for file in runtime.h runtime_sema.c runtime_thread.c; do
    git show "$ref:port/src/$file" > "$stock/$file"
done
for file in out/gpu/libtlggpu.so out/libatrac9.a out/isa_emulate.o; do
    [[ -f "$file" ]] || { echo "Missing $file: build fork first." >&2; exit 1; }
done
read -r -a includes <<< "$(pkg-config --cflags vulkan sdl3 libavcodec libavutil libswscale freetype2)"
read -r -a libraries <<< "$(pkg-config --libs vulkan sdl3 libavcodec libavutil libswscale freetype2)"
runtime=()
for file in src/runtime*.c; do
    case "$file" in
        src/runtime_thread.c|src/runtime_sema.c) ;;
        *) runtime+=("$file");;
    esac
done
runtime+=("$stock/runtime_thread.c" "$stock/runtime_sema.c")
cc=$(command -v cc)
if [[ -n "${CC:-}" ]]; then cc="$CC"; fi
"$cc" -std=c11 -O2 -g -Wall -Wextra -Werror -pthread -no-pie \
    ${includes[@]} -I. -Isrc -I"$stock" \
    src/probe.c ${runtime[@]} src/cpu_check.c src/vulkan_smoke.c \
    out/isa_emulate.o src/isa_rewrite.c out/libatrac9.a -lm \
    -Lout/gpu -ltlggpu -Wl,-rpath,'$ORIGIN/gpu' -Wl,-rpath,"$PWD/out/gpu" -rdynamic \
    ${libraries[@]} -o out/tlg-probe-stock
echo "Built $PWD/out/tlg-probe-stock (unmodified C runtime, same local GPU library)"
