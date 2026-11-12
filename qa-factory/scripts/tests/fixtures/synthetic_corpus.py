"""Helpers of the synthetic tracker corpus (fixtures/investigation-14857/): the part of it that git does not hold.

The text of the corpus is committed as files and tests read those files. The four screenshots of the run are not committed
(a binary file is a leak the scanner cannot read): `synthetic-derivations.json` records their names (= the sha256 of
their bytes), their sizes and the seed, and `materialize_blobs` rebuilds them byte for byte.

Imports nothing from docs/migration/: that folder does not travel with the package (spec t-1855-gm2-7 E10).
"""
import hashlib
import struct
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import hooklib  # noqa: E402

DERIVATIONS = HERE / "synthetic-derivations.json"
SIGNATURE = b"\x89PNG\r\n\x1a\n"
FILLER_TYPE = b"prVt"        # ancillary, private, reserved bit set, safe to copy: a decoder skips it
FRAME = 12                   # length + type + crc
IDAT_DATA = bytes.fromhex("789c63f80f0001010100")      # a fixed zlib stream of one grey pixel: no compressor is asked at run time


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _skeleton() -> bytes:
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    idat = _chunk(b"IDAT", IDAT_DATA)
    return SIGNATURE + ihdr + idat


def _filler(seed: int, length: int) -> bytes:
    """`length` bytes from sha256(seed || counter) blocks: defined by the SHA-256 standard, not by a library's generator."""
    out, counter = bytearray(), 0
    while len(out) < length:
        out += hashlib.sha256(struct.pack(">QQ", seed, counter)).digest()
        counter += 1
    return bytes(out[:length])


MIN_SIZE = len(_skeleton()) + FRAME


def synthetic_png(size: int, seed: int) -> bytes:
    """A valid PNG of exactly `size` bytes: signature, IHDR, IDAT of a one-pixel image, one private filler chunk with a
    right CRC (its bytes come from `seed`), IEND. Two seeds give two different files. A size too small for the frame
    is a ValueError naming the minimum."""
    head, end = _skeleton(), _chunk(b"IEND", b"")
    room = size - len(head) - len(end)
    if room < FRAME:
        raise ValueError(f"a PNG of {size} bytes cannot hold the frame: the minimum is {len(head) + len(end) + FRAME}")
    return head + _chunk(FILLER_TYPE, _filler(seed, room - FRAME)) + end


def derivations(path=None) -> dict:
    """The recorded derivations of the corpus: {fresh, stale, blobs, ...}. An unreadable file is a ValueError."""
    value = hooklib.read_json(path or DERIVATIONS, kind=dict)
    if value is None:
        raise ValueError(f"cannot read the derivations {path or DERIVATIONS}")
    return value


def materialize_blobs(task_root, path=None) -> list:
    """Write the recorded screenshots under `<task_root>/work/blobs/<sha256>.png`; the names written, sorted. A blob whose
    rebuilt bytes do not hash to its recorded name is a ValueError (the record and the helper have drifted)."""
    target = Path(task_root) / "work" / "blobs"
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for blob in derivations(path).get("blobs", []):
        data = synthetic_png(int(blob["size"]), int(blob["seed"]))
        digest = hashlib.sha256(data).hexdigest()
        if digest != blob["name"]:
            raise ValueError(f"blob {blob['name']}: the rebuilt bytes hash to {digest}")
        (target / (digest + ".png")).write_bytes(data)
        written.append(digest)
    return sorted(written)
