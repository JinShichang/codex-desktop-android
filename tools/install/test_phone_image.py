import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

import phone_image


class PhoneImageTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def archive(self, entries):
        path = self.root / "image.tar.gz"
        with tarfile.open(path, "w:gz", format=tarfile.USTAR_FORMAT) as out:
            for name, kind, content in entries:
                item = tarfile.TarInfo(name)
                item.type = kind
                item.mode = 0o755 if kind == tarfile.DIRTYPE else 0o644
                if kind == tarfile.REGTYPE:
                    item.size = len(content)
                    out.addfile(item, io.BytesIO(content))
                else:
                    if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                        item.linkname = content
                    out.addfile(item)
        return path

    def test_exact_archive_bounds(self):
        path = self.archive([(".", tarfile.DIRTYPE, b""), ("usr", tarfile.DIRTYPE, b""),
                             ("usr/example", tarfile.REGTYPE, b"hello")])
        spec = phone_image.inspect_archive(path, phone_image.digest(path))
        self.assertEqual(spec["members"], 3)
        self.assertEqual(spec["payloadBytes"], 5)
        self.assertEqual(spec["maxTarBytes"] % 512, 0)
        self.assertEqual(spec["compressedBytes"], path.stat().st_size)

    def test_tampered_input_refused(self):
        path = self.archive([(".", tarfile.DIRTYPE, b"")])
        with self.assertRaisesRegex(ValueError, "digest"):
            phone_image.inspect_archive(path, "0" * 64)

    def test_hardlinks_require_explicit_materialization(self):
        path = self.archive([(".", tarfile.DIRTYPE, b""), ("a", tarfile.REGTYPE, b"hello"),
                             ("b", tarfile.LNKTYPE, "a")])
        with self.assertRaisesRegex(ValueError, "hardlinks"):
            phone_image.inspect_archive(path, phone_image.digest(path))

    def test_link_parent_refused(self):
        path = self.archive([(".", tarfile.DIRTYPE, b""), ("usr", tarfile.SYMTYPE, "/tmp"),
                             ("usr/file", tarfile.REGTYPE, b"hello")])
        with self.assertRaisesRegex(ValueError, "parent"):
            phone_image.inspect_archive(path, phone_image.digest(path))

    def test_symlink_cannot_escape_guest(self):
        path = self.archive([(".", tarfile.DIRTYPE, b""), ("bad", tarfile.SYMTYPE, "../outside")])
        with self.assertRaisesRegex(ValueError, "leaves guest"):
            phone_image.inspect_archive(path, phone_image.digest(path))

    def test_guest_absolute_symlink_supported(self):
        path = self.archive([(".", tarfile.DIRTYPE, b""), ("link", tarfile.SYMTYPE, "/usr/bin")])
        self.assertEqual(phone_image.inspect_archive(path, phone_image.digest(path))["members"], 2)

    def test_user_profile_never_distributed(self):
        (self.root / "home").mkdir()
        phone_image.require_pristine_profile(self.root)
        (self.root / "home/codex").mkdir()
        with self.assertRaisesRegex(ValueError, "profile"):
            phone_image.require_pristine_profile(self.root)

    def test_missing_runtime_component_refused(self):
        for name in phone_image.RUNTIME_TREES:
            (self.root / name).mkdir(parents=True)
        with self.assertRaises(FileNotFoundError):
            phone_image.inventory(self.root)

    def test_traversal_and_ambiguous_paths_refused(self):
        for name in ("../x", "/usr/bin", "usr//bin", "usr/./bin", "usr/../bin", "usr\\bin", "usr/\nfile"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                phone_image.path_name(name)


if __name__ == "__main__":
    unittest.main()
