#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Controlled Fedora/RADV A/B: fork runtime, stock runtime, and upstream release.

Reuses the same prepared guest image and launcher environment, but makes
independent fresh save/cache folders. Does not alter existing game data.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

PORT = Path(__file__).resolve().parents[1]
RELEASE_TAG = "v2026.10.24-a2e69a1"
RELEASE_NAME = "gr2-linux-x86_64"
RELEASE_URL = ("https://github.com/HayatoG/gr2_pc/releases/download/"
               + RELEASE_TAG + "/" + RELEASE_NAME + ".tar.gz")
RELEASE_SHA256 = "543cf5ca9c21b9b3f9463c3d8f712e6eecd4a768fecbed5eecdcca57cfb03366"


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def metrics(log):
    """Frames rendered != visible game progress. No automatic success verdict."""
    def last(pattern):
        matches = re.findall(pattern, log)
        return matches[-1] if matches else None
    ajm = last(r"Runtime: Ajm batches=\d+, jobs=(\d+), ATRAC9 frames decoded=(\d+)")
    files = last(r"Runtime: files opened=\d+, reads=(\d+) \((\d+) bytes\)")
    return {
        "fps": last(r"Frame stats: ([\d.]+) FPS"),
        "ajm_jobs": int(ajm[0]) if ajm else None,
        "atrac9_frames": int(ajm[1]) if ajm else None,
        "file_reads": int(files[0]) if files else None,
        "bytes_read": int(files[1]) if files else None,
        "video_decoder_started": "VideoDecoderThread start" in log,
        "audio_decoder_started": "AudioDecoderThread start" in log,
        "active_wait_snapshots": log.count("Runtime: active waits (TLG_WAIT_ACTIVE"),
        "pending_semaphore_snapshots": log.count("Runtime: pending semaphores (TLG_WAIT_ACTIVE"),
        "stop_lines": [line[:300] for line in log.splitlines()
                       if line.startswith("STOP:")][:8],
    }


def download_release(cache, offline=False):
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / (RELEASE_NAME + ".tar.gz")
    if archive.exists() and digest(archive) != RELEASE_SHA256:
        raise RuntimeError("Invalid cached release hash; remove " + str(archive))
    if not archive.exists():
        if offline:
            raise RuntimeError("Official release not cached; omit --offline once")
        part = cache / (RELEASE_NAME + ".part")
        print("Downloading SHA256-verified official upstream release (~80 MB)...", flush=True)
        try:
            req = urllib.request.Request(RELEASE_URL, headers={"User-Agent": "gr2-ab-test"})
            with urllib.request.urlopen(req, timeout=120) as response, open(part, "wb") as out:
                shutil.copyfileobj(response, out)
            if digest(part) != RELEASE_SHA256:
                raise RuntimeError("Release SHA256 mismatch; refusing to execute")
            part.replace(archive)
        finally:
            part.unlink(missing_ok=True)
    return archive


def unpack_runtime(archive, cache):
    """Extract only necessary public release files, reject unsafe paths."""
    root = cache / "release-runtime"
    exe = root / "out" / "tlg-probe"
    gpu = root / "out" / "gpu" / "libtlggpu.so"
    if exe.is_file() and gpu.is_file():
        return exe
    with tarfile.open(archive, "r:gz") as archive_stream:
        for member in archive_stream:
            path = PurePosixPath(member.name)
            parts = path.parts
            if path.is_absolute() or any(part in (".", "..") for part in parts):
                raise RuntimeError("Invalid archive path: " + member.name)
            if len(parts) < 3 or parts[:2] != (RELEASE_NAME, "out"):
                continue
            relative = parts[2:]
            wanted = (relative in (("tlg-probe",), ("gpu", "libtlggpu.so"))
                      or (relative[0] == "lib" and len(relative) == 2))
            if not wanted:
                continue
            if not member.isfile() or member.size > 500 * 1024 * 1024:
                raise RuntimeError("Unexpected runtime archive member: " + member.name)
            target = root.joinpath("out", *relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            content = archive_stream.extractfile(member)
            if content is None:
                raise RuntimeError("Cannot read archive member " + member.name)
            with content, open(target, "wb") as dst:
                shutil.copyfileobj(content, dst)
            target.chmod(0o755 if relative in (("tlg-probe",), ("gpu", "libtlggpu.so"))
                         else 0o644)
    if not exe.is_file() or not gpu.is_file():
        raise RuntimeError("Release is missing the executable or GPU library")
    return exe


def launcher():
    sys.path.insert(0, str(PORT / "launcher"))
    import gr2_run
    return gr2_run


def command(exe, image, profile, patches, game, user, seconds, isa=None):
    args = [str(exe), str(image), "--app0", str(game), "--user", str(user),
            "--content-profile", str(profile), "--patches", str(patches),
            "--timeout", str(seconds)]
    if isa is not None and Path(isa).is_file():
        args += ["--isa-rewrite", str(isa)]
    return args


def run_variant(name, executable, run_dir, mod, settings, shared, seconds):
    user = run_dir / name
    user.mkdir()
    target_ini = user / "tlg.ini"
    original = mod.USER_DIR / "tlg.ini"
    if original.is_file():
        shutil.copyfile(original, target_ini)
    else:
        target_ini.write_text("# isolated comparison config\n", encoding="utf-8")
    env = mod.build_env(settings)
    for key in ("TLG_WAIT_STATS", "TLG_WAIT_ACTIVE", "TLG_TRACE_SEMA"):
        env.pop(key, None)
    env["TLG_CONFIG"] = str(target_ini)
    env["TLG_GPU_USER_DIR"] = str(user)
    env["GR2_GPU_USER_DIR"] = str(user)
    bundled = executable.parent / "lib"
    inherited = os.environ.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = os.pathsep.join(
        x for x in (str(bundled) if bundled.is_dir() else "", inherited) if x
    )
    # Capture which host shared libraries each candidate really resolves to.
    # This is often the key difference between the Fedora build and the CI package.
    if shutil.which("ldd"):
        for label, binary in (("probe", executable),
                              ("gpu", executable.parent / "gpu" / "libtlggpu.so")):
            try:
                resolved = subprocess.run(["ldd", str(binary)], cwd=user, env=env,
                                          capture_output=True, text=True, timeout=20)
                (user / ("ldd_" + label + ".txt")).write_text(
                    resolved.stdout + resolved.stderr, encoding="utf-8")
            except (OSError, subprocess.TimeoutExpired) as error:
                (user / ("ldd_" + label + ".txt")).write_text(
                    "ldd failed: " + str(error) + "\n", encoding="utf-8")
    image, profile, patches = shared
    cmd = command(executable, image, profile, patches, settings["game_dir"],
                  user, seconds, mod.ISA_TABLE)
    log_path = user / "run.log"
    print(f"Running {name} ({seconds}s). Watch whether the game is visible...", flush=True)
    with open(log_path, "w", encoding="utf-8") as log:
        try:
            result = subprocess.run(cmd, cwd=user, env=env, stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=subprocess.STDOUT,
                                    timeout=seconds + 40)
            status = result.returncode
        except subprocess.TimeoutExpired:
            log.write("\nDIAGNOSTIC: host timeout exceeded\n")
            status = "host-timeout"
    stats = metrics(log_path.read_text(encoding="utf-8", errors="replace"))
    stats.update({
        "exit_code": status,
        "executable_sha256": digest(executable),
        "gpu_sha256": digest(executable.parent / "gpu" / "libtlggpu.so"),
        "log": str(log_path),
    })
    print(f"  AJM jobs={stats['ajm_jobs']}; video started={stats['video_decoder_started']}"
          f"; log={log_path}", flush=True)
    return stats


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=45)
    parser.add_argument("--skip-stock", action="store_true")
    parser.add_argument("--skip-release", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)
    if not 10 <= args.seconds <= 300:
        parser.error("--seconds must be between 10 and 300")
    if not sys.platform.startswith("linux"):
        parser.error("this experiment currently supports Linux only")
    mod = launcher()
    settings = mod.load_settings()
    if os.environ.get("TLG_GAME_DIR"):
        settings["game_dir"] = os.environ["TLG_GAME_DIR"]
    problems = mod.check_game(settings["game_dir"])
    if problems:
        raise RuntimeError("Game configuration error: " + str(problems))
    shared = (mod.OUT_DIR / "boot-linked.bin", mod.OUT_DIR / "content.bin",
              mod.OUT_DIR / "patches.bin")
    for path in shared:
        if not path.is_file():
            raise RuntimeError("Missing " + str(path) + "; run the working game first")
    cache = mod.OUT_DIR / "ab-tests" / "_cache"
    run_dir = (mod.OUT_DIR / "ab-tests" /
               (datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                + "-" + str(os.getpid())))
    run_dir.mkdir(parents=True)
    variants = [("fork-local", mod.PROBE)]
    if not args.skip_stock:
        subprocess.run(["bash", str(PORT / "tools" / "build_stock_probe.sh")],
                       cwd=PORT, check=True)
        variants.append(("stock-local", mod.OUT_DIR / "tlg-probe-stock"))
    if not args.skip_release:
        official = download_release(cache, offline=args.offline)
        variants.append(("upstream-release", unpack_runtime(official, cache)))
    report = {
        "baseline_sha": "a2e69a1bc506865716cb4e16f2c50f047bf65e57",
        "official_release": RELEASE_TAG,
        "host": platform.platform(),
        "guest_input_sha256": {key: digest(path) for key, path in
                               zip(("image", "content", "patches"), shared)},
        "notes": "Fresh isolated user and GPU cache for each run; no gameplay conclusion from FPS",
        "cases": {},
    }
    for name, exe in variants:
        report["cases"][name] = run_variant(name, exe, run_dir, mod, settings,
                                           shared, args.seconds)
    summary = run_dir / "summary.json"
    summary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    # Package logs and loader results only; never archive temporary saves/caches.
    bundle = run_dir / "diagnostics.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.write(summary, arcname="summary.json")
        for name, _ in variants:
            for filename in ("run.log", "ldd_probe.txt", "ldd_gpu.txt"):
                evidence = run_dir / name / filename
                if evidence.is_file():
                    output.write(evidence, arcname=name + "/" + filename)
    print("\nDone. Summary:", summary)
    print("Evidence archive (no save files or shader caches):", bundle)
    print("Record which variant actually showed gameplay; FPS alone does not prove it.")
    print("Logs can include private local paths: review before sharing publicly.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        sys.exit("A/B test failed: " + str(exc))
