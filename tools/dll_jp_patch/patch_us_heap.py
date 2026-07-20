#!/usr/bin/env python3
"""In-place Japanese patcher for .NET #US (user-string) heaps.

Rewrites selected user strings inside AEC-ENDGAME_OVERHAUL mod DLLs with
Japanese text of exactly the same UTF-16 code-unit length (shorter text is
expanded at the <FILL> marker), so no metadata offsets ever change.

Usage (from the AEC-ENDGAME_OVERHAUL directory):
    python3 ../tools/dll_jp_patch/patch_us_heap.py [--check]

For every DLL listed in translations.json:
  * a .en.bak copy is created first if one does not exist yet
  * the CURRENT dll is used as the patch base (so already-good strings
    outside the table survive), but offsets/budgets are validated against
    the .en.bak original
  * each translated string must fit its budget; the remainder is filled
    with spaces at the <FILL> marker (keeping color tags like [FF7A00]
    contiguous with whatever the game appends after the string)
"""
import json, os, shutil, sys
import dnfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK = "--check" in sys.argv


def read_us_heap(path):
    pe = dnfile.dnPE(path)
    return bytes(pe.net.user_strings.__data__)


def blob_at(heap, off):
    """Return (prefix_len, byte_len) of the length-prefixed blob at off."""
    b = heap[off]
    if b < 0x80:
        return 1, b
    if (b & 0xC0) == 0x80:
        return 2, ((b & 0x3F) << 8) | heap[off + 1]
    return 4, ((b & 0x1F) << 24) | (heap[off + 1] << 16) | (heap[off + 2] << 8) | heap[off + 3]


def compose(parts, budget):
    fixed = sum(len(p) for p in parts if p != "<FILL>")
    pad = budget - fixed
    if pad < 0:
        raise ValueError(f"text too long by {-pad} units: {parts!r}")
    out = "".join(" " * pad if p == "<FILL>" else p for p in parts)
    if "<FILL>" not in parts:
        out += " " * pad
    assert len(out) == budget
    return out


def patch_dll(dll, entries):
    bak = dll + ".en.bak"
    if not os.path.exists(bak):
        if CHECK:
            print(f"  (check) would create {bak}")
        else:
            shutil.copy2(dll, bak)
            print(f"  created {bak}")

    src = bak if os.path.exists(bak) else dll
    heap_orig = read_us_heap(src)
    data = bytearray(open(dll, "rb").read())
    heap_cur = read_us_heap(dll)
    base = bytes(data).find(heap_cur)
    if base < 0:
        raise RuntimeError(f"{dll}: #US heap not found in file image")

    for e in entries:
        off, budget = e["off"], e["budget"]
        pfx, blen = blob_at(heap_orig, off)
        want = budget * 2 + 1
        if blen != want:
            raise RuntimeError(f"{dll}@{off}: blob len {blen} != expected {want} (budget {budget})")
        text = compose(e["parts"], budget)
        enc = text.encode("utf-16-le")
        assert len(enc) == budget * 2
        term = 1 if any(ord(c) > 0x7F for c in text) else 0
        pos = base + off + pfx
        if CHECK:
            old = data[pos:pos + budget * 2].decode("utf-16-le", errors="replace")
            print(f"  @{off:<6} {old[:34]!r} -> {text[:34]!r}")
        else:
            data[pos:pos + budget * 2] = enc
            data[pos + budget * 2] = term
    if not CHECK:
        open(dll, "wb").write(bytes(data))
        # verify round-trip
        heap_new = read_us_heap(dll)
        for e in entries:
            pfx, blen = blob_at(heap_new, e["off"])
            got = heap_new[e["off"] + pfx:e["off"] + pfx + (blen - 1) & ~1]
            got = heap_new[e["off"] + pfx:e["off"] + pfx + ((blen - 1) & ~1)].decode("utf-16-le")
            want = compose(e["parts"], e["budget"])
            if got != want:
                raise RuntimeError(f"{dll}@{e['off']}: verify failed: {got!r}")
        print(f"  patched + verified {len(entries)} strings")


def main():
    table = json.load(open(os.path.join(HERE, "translations.json"), encoding="utf-8"))
    for dll, entries in table.items():
        if dll.startswith("_"):
            continue
        print(f"== {dll}")
        if not os.path.exists(dll):
            raise SystemExit(f"missing {dll} — run from the AEC-ENDGAME_OVERHAUL directory")
        patch_dll(dll, entries)


if __name__ == "__main__":
    main()
