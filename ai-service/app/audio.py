from __future__ import annotations

import asyncio
import os
import tempfile

OGG_MAGIC = b"OggS"


def is_ogg(payload: bytes) -> bool:
    return payload.startswith(OGG_MAGIC)


async def _run_ffmpeg(ffmpeg_bin: str, args: list[str]) -> None:
    process = await asyncio.create_subprocess_exec(
        ffmpeg_bin,
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace")[-500:]
        raise RuntimeError(f"ffmpeg failed ({process.returncode}): {detail}")


async def to_wav_mono_16k(ffmpeg_bin: str, source: bytes, suffix: str = ".ogg") -> bytes:
    with tempfile.TemporaryDirectory() as folder:
        src = os.path.join(folder, f"in{suffix}")
        dst = os.path.join(folder, "out.wav")
        with open(src, "wb") as handle:
            handle.write(source)
        await _run_ffmpeg(
            ffmpeg_bin,
            ["-y", "-i", src, "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", dst],
        )
        with open(dst, "rb") as handle:
            return handle.read()


async def to_ogg_opus(ffmpeg_bin: str, source: bytes, suffix: str = ".opus") -> bytes:
    if is_ogg(source):
        return source
    with tempfile.TemporaryDirectory() as folder:
        src = os.path.join(folder, f"in{suffix}")
        dst = os.path.join(folder, "out.ogg")
        with open(src, "wb") as handle:
            handle.write(source)
        try:
            await _run_ffmpeg(ffmpeg_bin, ["-y", "-i", src, "-c:a", "copy", dst])
            with open(dst, "rb") as handle:
                wrapped = handle.read()
            if is_ogg(wrapped):
                return wrapped
        except RuntimeError:
            pass
        await _run_ffmpeg(
            ffmpeg_bin,
            ["-y", "-i", src, "-c:a", "libopus", "-b:a", "32k", "-application", "voip", "-vn", dst],
        )
        with open(dst, "rb") as handle:
            return handle.read()
