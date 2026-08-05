from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

FOCUS_PREVIEW_PROTOCOL = "eaw-focus-text-preview/1"
FocusPreviewPolicy = Literal["visual", "strict"]
GlyphPriority = Literal["ru", "en"]
PreviewStatus = Literal["green", "yellow", "red"]


class FocusPreviewError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FocusPreviewRequestItem:
    request_id: int
    key: str
    description: str
    glyph_priority: GlyphPriority


@dataclass(frozen=True, slots=True)
class FocusPreviewResult:
    request_id: int
    key: str
    status: PreviewStatus
    fits: bool
    fits_visual: bool
    fits_strict: bool
    description_lines: int
    description_height_px: int
    formal_overflow_px: int
    panel_overlap_px: int
    intersects_effect_panel: bool
    missing_glyphs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FocusPreviewItemError:
    request_id: int
    key: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class FocusPreviewBatchResult:
    protocol: str
    version: str
    results: tuple[FocusPreviewResult, ...]
    errors: tuple[FocusPreviewItemError, ...]
    total: int
    green: int
    yellow: int
    red: int
    failed_policy: int


def validate_focus_preview_installation(executable: Path) -> Path:
    resolved = executable.expanduser().resolve()
    if not resolved.is_file():
        raise FocusPreviewError(
            f"Не найден EaWFocusTextPreviewCLI.exe: {resolved}"
        )
    internal = resolved.parent / "_internal"
    if not internal.is_dir():
        raise FocusPreviewError(
            "Рядом с EaWFocusTextPreviewCLI.exe отсутствует папка "
            f"_internal: {internal}"
        )
    return resolved


def _as_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise FocusPreviewError(f"{label} не является JSON-объектом.")
    return value


def _as_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise FocusPreviewError(f"Поле {label} должно быть целым числом.")
    return value


def _as_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise FocusPreviewError(f"Поле {label} должно быть логическим.")
    return value


def _error_text(response: Mapping[str, Any]) -> str:
    error = response.get("error")
    if isinstance(error, Mapping):
        code = error.get("code", "unknown_error")
        message = error.get("message", "описание отсутствует")
        return f"{code}: {message}"
    return "CLI вернул ошибку без описания."


def _parse_result(
    payload: Mapping[str, Any],
    fallback: FocusPreviewRequestItem,
) -> FocusPreviewResult:
    status = payload.get("status")
    if status not in {"green", "yellow", "red"}:
        raise FocusPreviewError(
            f"CLI вернул неизвестный статус для {fallback.key}: {status!r}"
        )
    request_id = payload.get("id", fallback.request_id)
    if request_id != fallback.request_id:
        raise FocusPreviewError(
            "CLI вернул результат с неожиданным id: "
            f"ожидался {fallback.request_id}, получен {request_id!r}."
        )
    key = payload.get("key", fallback.key)
    if not isinstance(key, str):
        raise FocusPreviewError("Поле result.key должно быть строкой.")

    description = _as_mapping(
        payload.get("description"),
        "Поле result.description",
    )
    missing = payload.get("missing_glyphs", [])
    if (
        not isinstance(missing, list)
        or any(not isinstance(character, str) for character in missing)
    ):
        raise FocusPreviewError(
            "Поле result.missing_glyphs должно быть массивом строк."
        )

    return FocusPreviewResult(
        request_id=fallback.request_id,
        key=key,
        status=status,
        fits=_as_bool(payload.get("fits"), "result.fits"),
        fits_visual=_as_bool(
            payload.get("fits_visual"),
            "result.fits_visual",
        ),
        fits_strict=_as_bool(
            payload.get("fits_strict"),
            "result.fits_strict",
        ),
        description_lines=_as_int(
            description.get("lines"),
            "result.description.lines",
        ),
        description_height_px=_as_int(
            description.get("height_px"),
            "result.description.height_px",
        ),
        formal_overflow_px=_as_int(
            description.get("formal_overflow_px"),
            "result.description.formal_overflow_px",
        ),
        panel_overlap_px=_as_int(
            description.get("panel_overlap_px"),
            "result.description.panel_overlap_px",
        ),
        intersects_effect_panel=_as_bool(
            description.get("intersects_effect_panel"),
            "result.description.intersects_effect_panel",
        ),
        missing_glyphs=tuple(missing),
    )


class FocusPreviewClient:
    def __init__(
        self,
        executable: Path,
        *,
        timeout_seconds: int = 900,
    ) -> None:
        self.executable = validate_focus_preview_installation(executable)
        self.timeout_seconds = timeout_seconds

    def check(
        self,
        items: Iterable[FocusPreviewRequestItem],
        *,
        policy: FocusPreviewPolicy,
    ) -> FocusPreviewBatchResult:
        if policy not in {"visual", "strict"}:
            raise FocusPreviewError(f"Неизвестная политика CLI: {policy}")
        requested = tuple(items)
        if not requested:
            return FocusPreviewBatchResult(
                protocol=FOCUS_PREVIEW_PROTOCOL,
                version="",
                results=(),
                errors=(),
                total=0,
                green=0,
                yellow=0,
                red=0,
                failed_policy=0,
            )

        payload = {
            "policy": policy,
            "items": [
                {
                    "id": item.request_id,
                    "key": item.key,
                    "description": item.description,
                    "glyph_priority": item.glyph_priority,
                }
                for item in requested
            ],
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        creationflags = 0
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            process = subprocess.run(
                [str(self.executable), "check", "-"],
                input=encoded,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(self.executable.parent),
                shell=False,
                creationflags=creationflags,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise FocusPreviewError(
                "EaW Focus Text Preview не завершил проверку за "
                f"{self.timeout_seconds} секунд."
            ) from error
        except OSError as error:
            raise FocusPreviewError(
                f"Не удалось запустить EaW Focus Text Preview: {error}"
            ) from error

        try:
            stdout = process.stdout.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as error:
            raise FocusPreviewError(
                "EaW Focus Text Preview вернул повреждённый UTF-8."
            ) from error
        try:
            response_value = json.loads(stdout)
        except json.JSONDecodeError as error:
            stderr = process.stderr.decode("utf-8", errors="replace").strip()
            details = f" Stderr: {stderr}" if stderr else ""
            raise FocusPreviewError(
                "EaW Focus Text Preview не вернул корректный JSON."
                f"{details}"
            ) from error
        if process.returncode not in {0, 1, 2}:
            raise FocusPreviewError(
                "EaW Focus Text Preview завершился с неожиданным кодом "
                f"{process.returncode}."
            )

        response = _as_mapping(response_value, "Ответ CLI")
        protocol = response.get("protocol")
        if protocol != FOCUS_PREVIEW_PROTOCOL:
            raise FocusPreviewError(
                "Несовместимый протокол EaW Focus Text Preview: "
                f"{protocol!r}; ожидался {FOCUS_PREVIEW_PROTOCOL!r}."
            )
        version = response.get("version", "")
        if not isinstance(version, str):
            raise FocusPreviewError("Поле version в ответе CLI не является строкой.")

        raw_results = response.get("results")
        if not isinstance(raw_results, list):
            raise FocusPreviewError(
                "EaW Focus Text Preview отклонил пакет: "
                f"{_error_text(response)}"
            )
        if len(raw_results) != len(requested):
            raise FocusPreviewError(
                "CLI вернул другое количество результатов: "
                f"{len(raw_results)} вместо {len(requested)}."
            )

        results: list[FocusPreviewResult] = []
        errors: list[FocusPreviewItemError] = []
        requested_by_id = {
            item.request_id: item
            for item in requested
        }
        seen_ids: set[int] = set()
        for position, raw_entry in enumerate(raw_results):
            entry = _as_mapping(raw_entry, "Элемент results")
            if entry.get("ok") is True:
                result_payload = _as_mapping(
                    entry.get("result"),
                    "Поле results[].result",
                )
                response_id = result_payload.get("id")
                fallback = requested_by_id.get(response_id)
                if fallback is None:
                    fallback = requested[position]
                if fallback.request_id in seen_ids:
                    raise FocusPreviewError(
                        "CLI вернул повторяющийся id результата: "
                        f"{fallback.request_id}."
                    )
                seen_ids.add(fallback.request_id)
                results.append(_parse_result(result_payload, fallback))
                continue

            error = entry.get("error")
            error_payload = error if isinstance(error, Mapping) else {}
            response_id = entry.get("id")
            fallback = requested_by_id.get(response_id)
            if fallback is None:
                fallback = requested[position]
            if fallback.request_id in seen_ids:
                raise FocusPreviewError(
                    "CLI вернул повторяющийся id результата: "
                    f"{fallback.request_id}."
                )
            seen_ids.add(fallback.request_id)
            error_id = fallback.request_id
            error_key = entry.get("key", fallback.key)
            if not isinstance(error_key, str):
                error_key = fallback.key
            errors.append(
                FocusPreviewItemError(
                    request_id=error_id,
                    key=error_key,
                    code=str(error_payload.get("code", "unknown_error")),
                    message=str(
                        error_payload.get(
                            "message",
                            "CLI не указал причину ошибки.",
                        )
                    ),
                )
            )
        if seen_ids != set(requested_by_id):
            missing_ids = sorted(set(requested_by_id) - seen_ids)
            raise FocusPreviewError(
                "CLI не вернул результаты для id: "
                + ", ".join(map(str, missing_ids[:10]))
            )

        counts = {
            status: sum(result.status == status for result in results)
            for status in ("green", "yellow", "red")
        }
        failed_policy = sum(not result.fits for result in results) + len(errors)
        return FocusPreviewBatchResult(
            protocol=protocol,
            version=version,
            results=tuple(results),
            errors=tuple(errors),
            total=len(requested),
            green=counts["green"],
            yellow=counts["yellow"],
            red=counts["red"],
            failed_policy=failed_policy,
        )
