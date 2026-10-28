"""Reading and changing the settings row. Each change raises the version; a process compares
the version at the start of each piece of work and reads the settings again when it changed.

A secret is stored under its name: a SecretName, or TRIGGER_SECRET and the name of a trigger
secret. The name is also bound into its encryption."""

import logging
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yaksh.db.models import StoredSettings
from yaksh.domain.errors import ConflictError, ValidationError
from yaksh.domain.settings import (
    KEY_URLS,
    AppSettings,
    SecretName,
    Secrets,
    SettingsValues,
    is_secret_name,
)
from yaksh.settings.cipher import Cipher

log = logging.getLogger(__name__)

DEFAULTS = SettingsValues().model_dump(mode="json")


def changed_values(values: SettingsValues) -> dict[str, Any]:
    """The values that differ from the defaults: only those are stored, so a release can
    change a default."""
    changed: dict[str, Any] = {}
    for section, fields in values.model_dump(mode="json", include=set(DEFAULTS)).items():
        diff = {key: value for key, value in fields.items() if DEFAULTS[section][key] != value}
        if diff:
            changed[section] = diff
    return changed


def merged(base: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in changes.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), Mapping):
            out[key] = merged(out[key], value)
        else:
            out[key] = value
    return out


def validated(version: int, values: Mapping[str, Any], secrets: Mapping[str, str]) -> AppSettings:
    return AppSettings.model_validate(
        {**values, "version": version, "secrets": Secrets.from_flat(secrets)}
    )


def build(version: int, values: Mapping[str, Any], secrets: Mapping[str, str]) -> AppSettings:
    """The settings, or a ValidationError that names each problem."""
    try:
        return validated(version, values, secrets)
    except PydanticValidationError as error:
        raise ValidationError(problems(error)) from None


def problems(error: PydanticValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}"
        for issue in error.errors()
    )


def planned(
    settings: AppSettings,
    values: Mapping[str, Any] | None = None,
    secrets: Mapping[str, str | None] | None = None,
) -> AppSettings:
    """The settings after the changes, without saving them: values replace the fields they
    name, by section; a secret set to None is removed; a new base URL removes the key sent to
    it, unless the same change saves a new key. Raises ValidationError."""
    secrets = secrets or {}
    unknown = [name for name in secrets if not is_secret_name(name)]
    if unknown:
        raise ValidationError("; ".join(f"{name}: no such secret" for name in unknown))
    current = settings.model_dump(mode="json", include=set(DEFAULTS))
    after = merged(current, values or {})
    flat = settings.secrets.flat()
    for key, (section, field) in KEY_URLS.items():
        if after[section][field] != current[section][field] and key not in secrets:
            flat.pop(key, None)
    flat = {name: value for name, value in flat.items() if name not in secrets}
    flat |= {name: value for name, value in secrets.items() if value is not None}
    return build(settings.version + 1, after, flat)


def address(settings: AppSettings, name: str) -> str:
    section, field = KEY_URLS[SecretName(name)]
    return getattr(getattr(settings, section), field)


async def stored_version(session: AsyncSession) -> int:
    return await session.scalar(select(StoredSettings.version)) or 0


async def load(session: AsyncSession, cipher: Cipher) -> AppSettings:
    """The stored settings. A stored value that this release refuses, such as one outside a
    narrower range, is dropped with a warning, so its default applies and the Settings page
    can still open; writes stay strict."""
    row = await session.get_one(StoredSettings, 1, populate_existing=True)
    secrets = {name: cipher.decrypt(name, value) for name, value in row.secrets.items()}
    try:
        return validated(row.version, row.values, secrets)
    except PydanticValidationError as error:
        refused = {tuple(issue["loc"][:2]) for issue in error.errors()}
        log.warning("stored settings use their defaults for %s", problems(error))
        values = {
            section: {key: value for key, value in fields.items() if (section, key) not in refused}
            for section, fields in row.values.items()
            if section in DEFAULTS
        }
        return validated(row.version, values, secrets)


async def change(
    session: AsyncSession,
    cipher: Cipher,
    *,
    values: Mapping[str, Any] | None = None,
    secrets: Mapping[str, str | None] | None = None,
    checked: AppSettings | None = None,
) -> AppSettings:
    """Save planned() of the stored settings in one step, or nothing. A secret that did not
    change keeps its stored encryption. `checked` is the settings a provider checked the new
    keys with: a key whose address changed since then is not saved, so it never goes to an
    address it was not checked at."""
    row = await session.get_one(StoredSettings, 1, with_for_update=True, populate_existing=True)
    candidate = planned(await load(session, cipher), values, secrets)
    changed = secrets or {}
    if checked is not None:
        moved = [
            name
            for name, value in changed.items()
            if value is not None
            and name in KEY_URLS
            and address(candidate, name) != address(checked, name)
        ]
        if moved:
            await session.rollback()
            raise ConflictError(
                f"the address of {', '.join(moved)} changed while it was checked; try again"
            )
    stored = {
        name: row.secrets[name]
        if name in row.secrets and name not in changed
        else cipher.encrypt(name, value)
        for name, value in candidate.secrets.flat().items()
    }
    await session.execute(
        update(StoredSettings)
        .where(StoredSettings.id == 1)
        .values(version=candidate.version, values=changed_values(candidate), secrets=stored)
    )
    await session.commit()
    return candidate


class SettingsSource:
    """The current settings of one process: read again only when the stored version moved."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], cipher: Cipher) -> None:
        self._sessionmaker = sessionmaker
        self._cipher = cipher
        self._settings: AppSettings | None = None

    @property
    def cipher(self) -> Cipher:
        return self._cipher

    @property
    def latest(self) -> AppSettings | None:
        """The settings as last read, without a database round trip; None before the first
        read."""
        return self._settings

    async def current(self) -> AppSettings:
        async with self._sessionmaker() as session:
            version = await stored_version(session)
            if self._settings is None or self._settings.version != version:
                self._settings = await load(session, self._cipher)
        return self._settings
