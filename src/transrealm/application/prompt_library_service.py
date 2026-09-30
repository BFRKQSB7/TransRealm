"""Named prompt copies; effective prompts still use the existing override contract."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from threading import RLock
from uuid import uuid4

from transrealm.application.model_profile_service import ModelProfileService
from transrealm.application.preset_templates import ALLOWED_PLACEHOLDERS, current_preset
from transrealm.domain.model_profile import ModelProfile
from transrealm.domain.prompt_override import (
    PromptOverride,
    PromptOverrideError,
    validate_override_template,
)


@dataclass(frozen=True)
class NamedPrompt:
    template_id: str
    name: str
    parent_template_version: str
    template_text: str


class PromptLibraryService:
    """Private, atomic template library beside the database, without schema changes.

    Applying a copy persists its effective text in PromptOverride, which remains
    the authoritative input to rendering and historical Attempt snapshots.
    Deleting or editing a library copy never rewrites an existing override.
    """

    _locks: dict[Path, RLock] = {}
    _registry_lock = RLock()

    def __init__(self, db_path: Path, *, app_version: str) -> None:
        self._db_path = db_path
        self._app_version = app_version
        self.path = db_path.with_suffix(".prompts.json")
        with self._registry_lock:
            self._lock = self._locks.setdefault(self.path.resolve(), RLock())

    def list_templates(self) -> list[NamedPrompt]:
        with self._lock:
            return self._read()

    def list_models(self) -> list[ModelProfile]:
        with ModelProfileService(self._db_path, app_version=self._app_version) as service:
            return service.list_profiles()

    def model_prompt(self, profile_id: int) -> PromptOverride | None:
        with ModelProfileService(self._db_path, app_version=self._app_version) as service:
            return service.get_prompt_override(profile_id)

    def save_model_prompt(self, profile_id: int, text: str) -> PromptOverride:
        with ModelProfileService(self._db_path, app_version=self._app_version) as service:
            return service.set_prompt_override(profile_id, text)

    def clear_model_prompt(self, profile_id: int) -> bool:
        with ModelProfileService(self._db_path, app_version=self._app_version) as service:
            return service.clear_prompt_override(profile_id)

    def copy_preset(self, name: str, *, template_text: str | None = None) -> NamedPrompt:
        preset = current_preset()
        prompt = NamedPrompt(
            uuid4().hex,
            name.strip(),
            preset.version,
            preset.template_text if template_text is None else template_text,
        )
        self._validate(prompt)
        with self._lock:
            prompts = self._read()
            self._check_name(prompt, prompts)
            self._write([*prompts, prompt])
        return prompt

    def update(self, template_id: str, *, name: str, template_text: str) -> NamedPrompt:
        with self._lock:
            prompts = self._read()
            old = self._find(template_id, prompts)
            self._check_parent(old)
            prompt = replace(old, name=name.strip(), template_text=template_text)
            self._validate(prompt)
            self._check_name(prompt, prompts)
            self._write([prompt if item.template_id == template_id else item for item in prompts])
        return prompt

    def delete(self, template_id: str) -> None:
        with self._lock:
            prompts = self._read()
            self._find(template_id, prompts)
            self._write([item for item in prompts if item.template_id != template_id])

    def apply(self, profile_id: int, template_id: str | None) -> None:
        with self._lock:
            prompt = self._find(template_id, self._read()) if template_id is not None else None
            if prompt is not None:
                self._check_parent(prompt)
                self._validate(prompt)
            with ModelProfileService(self._db_path, app_version=self._app_version) as service:
                if service.get_profile(profile_id) is None:
                    raise PromptOverrideError("Select an existing model first.")
                if prompt is None:
                    service.clear_prompt_override(profile_id)
                else:
                    service.set_prompt_override(profile_id, prompt.template_text)

    @staticmethod
    def _find(template_id: str, prompts: list[NamedPrompt]) -> NamedPrompt:
        for prompt in prompts:
            if prompt.template_id == template_id:
                return prompt
        raise PromptOverrideError("This prompt no longer exists. Refresh the prompt list.")

    @staticmethod
    def _check_parent(prompt: NamedPrompt) -> None:
        if prompt.parent_template_version != current_preset().version:
            raise PromptOverrideError(
                "This prompt is based on an older preset. "
                "Copy the current preset before applying it."
            )

    @staticmethod
    def _validate(prompt: NamedPrompt) -> None:
        if not prompt.name or len(prompt.name) > 120:
            raise PromptOverrideError("Prompt name must contain 1 to 120 characters.")
        if not prompt.template_id or not prompt.parent_template_version:
            raise PromptOverrideError("Prompt metadata is invalid.")
        validate_override_template(prompt.template_text, allowed_placeholders=ALLOWED_PLACEHOLDERS)

    @staticmethod
    def _check_name(prompt: NamedPrompt, prompts: list[NamedPrompt]) -> None:
        if any(
            item.template_id != prompt.template_id
            and item.name.casefold() == prompt.name.casefold()
            for item in prompts
        ):
            raise PromptOverrideError("A prompt with this name already exists.")

    def _read(self) -> list[NamedPrompt]:
        if not self.path.exists():
            return []
        try:
            if self.path.stat().st_size > 4 * 1024 * 1024:
                raise ValueError
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("schema_version") != 1:
                raise ValueError
            records = payload["templates"]
            if not isinstance(records, list):
                raise ValueError
            prompts: list[NamedPrompt] = []
            for record in records:
                if not isinstance(record, dict) or not all(
                    isinstance(record.get(key), str)
                    for key in ("template_id", "name", "parent_template_version", "template_text")
                ):
                    raise ValueError
                prompt = NamedPrompt(**record)
                self._validate(prompt)
                if any(item.template_id == prompt.template_id for item in prompts):
                    raise ValueError
                self._check_name(prompt, prompts)
                prompts.append(prompt)
            return prompts
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise PromptOverrideError(
                "The prompt library could not be read. Restore its backup before making changes."
            ) from exc

    def _write(self, prompts: list[NamedPrompt]) -> None:
        payload = json.dumps(
            {"schema_version": 1, "templates": [asdict(item) for item in prompts]},
            ensure_ascii=False,
            indent=2,
        )
        if len(payload.encode("utf-8")) > 4 * 1024 * 1024:
            raise PromptOverrideError("The prompt library is full. Remove unused prompt copies.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = stream.name
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None and Path(temporary).exists():
                Path(temporary).unlink()
