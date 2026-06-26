"""Quick perf check of the per-file cascade vs. the prior sequential-phase design.

Uses synthetic files (mp3 + m4a) and a fake mutagen that simulates the cost
of an actual mutagen.File() open + parse (we sleep to model real I/O).
"""
import tempfile
import time
from pathlib import Path

from src.audio import cascade
from src.audio.cascade import CascadeTier


def make_tree(root: Path, n_t1: int, n_t3: int) -> None:
    for i in range(n_t1):
        (root / f"track_{i:05d}.mp3").write_bytes(b"\x00" * 1024)
    sub = root / "ambiguous-album"
    sub.mkdir()
    for i in range(n_t3):
        # m4a extension is ambiguous → forces Tier 3 in the cascade.
        (sub / f"track_{i:05d}.m4a").write_bytes(b"\x00" * 1024)


class FakeMutagen:
    """Pretend to do mutagen.File() work — model 200µs of CPU + 500µs of I/O."""

    PER_CALL_US = 700

    def __init__(self, path):
        import time as _t
        _t.sleep(self.PER_CALL_US / 1_000_000)
        self.info = type("Info", (), {"codec": "alac"})()


def main() -> None:
    N_T1 = 1000
    N_T3 = 4000

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        make_tree(root, N_T1, N_T3)
        files = sorted(root.rglob("*.mp3")) + sorted(root.rglob("*.m4a"))
        assert len(files) == N_T1 + N_T3

        # Patch mutagen.File via the inspector shim so cascade_with_tier picks it up.
        import src.audio.inspector as _shim
        from src.audio.mutagen_probe import _is_lossy_by_mutagen as _real_mutagen

        def fake_mutagen(file):
            return _real_mutagen.__wrapped__(file) if hasattr(_real_mutagen, "__wrapped__") else None

        # We patch the resolution: insert a fake mutagen before the cascade imports.
        # The cascade does `_resolve_tier("_is_lossy_by_mutagen", _mutagen_impl)` at
        # call time, looking up `src.audio.inspector._is_lossy_by_mutagen`.
        def fake_mutagen_impl(file):
            FakeMutagen(file)
            return False  # flac-like

        _shim._is_lossy_by_mutagen = fake_mutagen_impl

        # Warm up
        for f in files[:3]:
            cascade.cascade_with_tier(f)

        # Sequential baseline
        t0 = time.perf_counter()
        results = [cascade.cascade_with_tier(f) for f in files]
        seq_elapsed = (time.perf_counter() - t0) * 1000
        tier_counts = {t: 0 for t in CascadeTier}
        for _, tier in results:
            tier_counts[tier] += 1
        print(f"sequential:    {seq_elapsed:6.1f} ms, tiers={dict(tier_counts)}")

        from concurrent.futures import ThreadPoolExecutor

        for w in (4, 8, 16, 32):
            t0 = time.perf_counter()
            with ThreadPoolExecutor(max_workers=w) as ex:
                results = list(ex.map(cascade.cascade_with_tier, files))
            par_elapsed = (time.perf_counter() - t0) * 1000
            tier_counts = {t: 0 for t in CascadeTier}
            for _, tier in results:
                tier_counts[tier] += 1
            print(f"parallel (w={w:>2}): {par_elapsed:6.1f} ms, tiers={dict(tier_counts)}, speedup: {seq_elapsed / par_elapsed:.2f}x")


if __name__ == "__main__":
    main()