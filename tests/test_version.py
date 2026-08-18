import unittest

from hoi4_l10n_checker.version import DISPLAY_VERSION, __version__


class VersionTests(unittest.TestCase):
    def test_beta_version_is_consistent(self) -> None:
        self.assertEqual(__version__, "0.9.6F6-beta")
        self.assertEqual(DISPLAY_VERSION, "0.9.6F6 Beta")


if __name__ == "__main__":
    unittest.main()
