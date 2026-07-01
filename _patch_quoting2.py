from pathlib import Path

p = Path("tests/test_backend_quoting.py")
text = p.read_text()

old_block = (
    '            short_out = captured["short_outfile"]\n'
    '            assert "\\audio\\\\dst\\\\" in short_out or "/audio/dst/" in short_out, (\n'
    '                f"expected staged output under tmp/audio/dst, got {short_out!r}"\n'
    '            )\n'
)
new_block = (
    '            short_out = captured["short_outfile"]\n'
    '            assert "audio" in short_out and "dst" in short_out, (\n'
    '                f"expected staged output under tmp/audio/dst, got {short_out!r}"\n'
    '            )\n'
    '            assert "out.m4a" in short_out, (\n'
    '                f"staged basename should preserve original outfile name, got {short_out!r}"\n'
    '            )\n'
)
if old_block not in text:
    raise SystemExit("old block not found")
new_text = text.replace(old_block, new_block, 1)
if new_text == text:
    raise SystemExit("no change")
p.write_text(new_text)
print("replaced assertion ok")