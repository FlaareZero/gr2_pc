# Jirga crowd: exact texture-set cache reuse

## Why this patch exists

In the uploaded Fedora/RADV REMBRANDT \`jirga-hotpath.log\`:
- 11 heavy five-second intervals (>3,500 draws/frame) have medians around
  **6,193 draws/frame** and **13.3 FPS**.
- 128 heavy-frame stall reports have median **52.15 ms GPU tick wait**,
  **20.25 ms GPU command-thread CPU time**, and **0.4 ms recorder wait**.
- The render-state diagnostics repeatedly show ~27,000-48,000 misses of
  read-only *texture sets* caused by the **global texture registry
  generation**, often several times the number of key misses.
- 0 shader/pipeline compilations in the heavy samples.

These misses trigger expensive re-resolution of images and descriptor/view
state. This work is repeated even when the image that an NPC uses was
not itself removed or changed.

## What is optimized

The existing texture cache has a narrow safe rule in
TextureCache::FindImage: a *registered exact-match* image can remain
reusable after unrelated images enter or leave the registry.

We apply the same principle to the rasterizer's prepared read-only texture
sets, only when \`TLG_TEXTURE_SET_EXACT=1\`.

A stale set after a registry change is eligible only if all entries:
- Match the original shader stage and the exact prepared texture hashes.
- Resolve to live registered images with unchanged unique image UIDs (no
  recycled image slots).
- Were native, exact original images at cache fill time, not an overlap
  view, a scene proxy, or a null image.
- Still pass the existing backing, up-to-date, binding/rebind, layout,
  proxy and upscaler checks before use.

The patch NEVER removes guest draws or NPCs, changes shader programs,
relaxes GPU fences, or skips necessary image transitions. The normal
behavior is unchanged unless the variable is explicitly enabled.

The benefit is not guaranteed: even eliminating these misses cannot by
itself guarantee 30 FPS if the integrated GPU is saturated.

## Test and quick rollback

Preserve the two currently working binaries, with GR2 closed:

    cd ~/Scaricati/gr2-debug
    mkdir -p port/out/backup-before-texture-exact
    cp -a port/out/tlg-probe port/out/backup-before-texture-exact/
    cp -a port/out/gpu/libtlggpu.so port/out/backup-before-texture-exact/

Switch and build the new branch:

    git fetch origin
    git switch --track origin/perf/jirga-texture-generation-cache
    cd port
    TLG_BUILD_JOBS=3 TLG_LTO=OFF TLG_PGO=off bash build.sh
    cd ..

Two 90-second test runs from the same save and viewpoint, shader cache
already warm:

    TLG_TEXTURE_SET_EXACT=0 TLG_PRECISE_BUFFER_STAGES=0 TLG_RECORD_BATCH_KB=32 ./run_gr2.sh 90 > "$HOME/jirga-cache-off.log" 2>&1
    TLG_TEXTURE_SET_EXACT=1 TLG_PRECISE_BUFFER_STAGES=0 TLG_RECORD_BATCH_KB=32 ./run_gr2.sh 90 > "$HOME/jirga-cache-on.log" 2>&1

This isolates the new cache behavior inside the same freshly compiled
binary. Compare only intervals of similar crowd density/draw count.
Check that NPCs, shadows, texture appearance and save/load are correct.

In the log, compare:
- \`Render state memo: ... texture sets: X hits, Y misses\`
- \`texture set misses: ... generation ...; exact cross-generation validations Z\`
- \`Frame stats: FPS, ... draws/frame\`
- \`Frame pacing: median ... p99 ...\`

\`Z > 0\` means the new path activated, but **not** that FPS improved.
If images flicker, turn the flag off immediately without a rebuild:

    TLG_TEXTURE_SET_EXACT=0 ./run_gr2.sh

To restore *all* old compiled code (game must be closed):

    cp -a port/out/backup-before-texture-exact/tlg-probe port/out/tlg-probe
    cp -a port/out/backup-before-texture-exact/libtlggpu.so port/out/gpu/libtlggpu.so

This feature is experimental, not a release-ready FPS fix. Do not merge
PR #4 until the GPU build succeeds and visual correctness and A/B
performance are confirmed on the affected hardware.
