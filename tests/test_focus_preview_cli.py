from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hoi4_l10n_checker.focus_preview_cli import (
    FOCUS_PREVIEW_PROTOCOL,
    FocusPreviewClient,
    FocusPreviewError,
    FocusPreviewRequestItem,
    validate_focus_preview_installation,
)


class FocusPreviewClientTests(unittest.TestCase):
    @staticmethod
    def create_installation(root: Path) -> Path:
        executable = root / "EaWFocusTextPreviewCLI.exe"
        executable.write_bytes(b"placeholder")
        (root / "_internal").mkdir()
        return executable

    def test_installation_requires_internal_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "EaWFocusTextPreviewCLI.exe"
            executable.write_bytes(b"placeholder")

            with self.assertRaises(FocusPreviewError):
                validate_focus_preview_installation(executable)

    def test_batch_uses_utf8_stdin_and_accepts_exit_code_one(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = self.create_installation(Path(temporary))
            response = {
                "protocol": FOCUS_PREVIEW_PROTOCOL,
                "version": "0.7.5",
                "ok": True,
                "results": [
                    {
                        "ok": True,
                        "result": {
                            "id": 7,
                            "key": "FOCUS_A_desc",
                            "status": "red",
                            "fits": False,
                            "fits_visual": False,
                            "fits_strict": False,
                            "description": {
                                "lines": 7,
                                "height_px": 126,
                                "formal_overflow_px": 56,
                                "panel_overlap_px": 13,
                                "intersects_effect_panel": True,
                            },
                            "missing_glyphs": ["🦄"],
                        },
                    }
                ],
                "summary": {
                    "total": 1,
                    "green": 0,
                    "yellow": 0,
                    "red": 1,
                    "errors": 0,
                    "failed_policy": 1,
                },
            }
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout=json.dumps(
                    response,
                    ensure_ascii=False,
                ).encode("utf-8"),
                stderr=b"",
            )

            with patch(
                "hoi4_l10n_checker.focus_preview_cli.subprocess.run",
                return_value=completed,
            ) as run:
                result = FocusPreviewClient(executable).check(
                    [
                        FocusPreviewRequestItem(
                            request_id=7,
                            key="FOCUS_A_desc",
                            description='Кавычки "§Yтекст§!" и 5%',
                            glyph_priority="ru",
                        )
                    ],
                    policy="visual",
                )

            self.assertEqual(1, result.red)
            self.assertEqual("0.7.5", result.version)
            self.assertEqual(("🦄",), result.results[0].missing_glyphs)
            kwargs = run.call_args.kwargs
            request = json.loads(kwargs["input"].decode("utf-8"))
            self.assertEqual("visual", request["policy"])
            self.assertEqual(
                'Кавычки "§Yтекст§!" и 5%',
                request["items"][0]["description"],
            )
            self.assertFalse(kwargs["shell"])
            self.assertEqual(
                [str(executable.resolve()), "check", "-"],
                run.call_args.args[0],
            )


if __name__ == "__main__":
    unittest.main()
