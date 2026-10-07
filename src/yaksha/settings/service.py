"""What the Settings page and the CLI do with the settings: check a key with its provider before
it is saved, test the saved settings, and import or export them as a YAML document."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import yaml

from yaksha.domain.errors import ValidationError
from yaksha.domain.settings import TRIGGER_SECRET, AppSettings, SecretName, is_secret_name
from yaksha.evaluation.jev import JEV_MODEL
from yaksha.integrations import provider_checks as checks
from yaksha.integrations.provider_checks import ProviderCheckError
from yaksha.settings.store import DEFAULTS, changed_values
from yaksha.simulation.voices import builtin_voices

MAX_SECRET_CHARS = 4000
SECRET_NAMES = {name.value for name in SecretName}
PLACEHOLDER = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
DOCUMENT_HEADER = (
    "# Yaksha settings. Values not listed keep their defaults.\n"
    "# A secret is ${NAME}: the CLI reads NAME from its environment when it applies the file.\n"
)


class Provider(StrEnum):
    LLM = "llm"
    DEEPGRAM = "deepgram"
    ELEVENLABS = "elevenlabs"
    TYPESAFE = "typesafe"
    PLIVO = "plivo"


def check_voice() -> str:
    return builtin_voices()[0].provider_voice_id


async def test_provider(settings: AppSettings, provider: Provider) -> str:
    """Use the saved settings of one provider for a small piece of real work; the result says
    what worked. Raises ProviderCheckError."""
    secrets = settings.secrets
    match provider:
        case Provider.LLM:
            key = required(secrets.llm_api_key, "the LLM provider key")
            await checks.check_llm(
                settings.llm.base_url, key, settings.caller.model, settings.caller.reasoning_effort
            )
            return f"{settings.caller.model} answered a test request."
        case Provider.DEEPGRAM:
            key = required(secrets.deepgram_api_key, "the Deepgram key")
            await checks.check_deepgram(settings.deepgram.base_url, key, settings.deepgram.model)
            return f"Deepgram {settings.deepgram.model} transcribed a test clip."
        case Provider.ELEVENLABS:
            key = required(secrets.elevenlabs_api_key, "the ElevenLabs key")
            await checks.check_elevenlabs(key, check_voice())
            return "ElevenLabs spoke a test word."
        case Provider.TYPESAFE:
            key = required(secrets.typesafe_api_key, "the TypeSafe key")
            await checks.check_typesafe(key, JEV_MODEL)
            return "TypeSafe answered a test question."
        case Provider.PLIVO:
            credentials = settings.plivo_credentials
            if credentials is None:
                raise ProviderCheckError("the Plivo Auth ID and Auth token are not both saved")
            count = await checks.check_plivo(*credentials)
            return f"Yaksha reached the Plivo account; it lists {count} numbers."


def required(secret: Any, what: str) -> str:
    if secret is None:
        raise ProviderCheckError(f"{what} is not saved")
    return secret.get_secret_value()


async def check_secrets(candidate: AppSettings, changed: Mapping[str, str | None]) -> None:
    """Check each new key with its provider, with the candidate settings around it, before
    anything is saved. The Plivo Auth ID and Auth token are checked together. Raises
    ProviderCheckError, naming the key."""
    plivo = False
    for name, value in changed.items():
        if value is None:
            continue
        try:
            match name:
                case SecretName.LLM_API_KEY:
                    await checks.llm_models(candidate.llm.base_url, value)
                case SecretName.DEEPGRAM_API_KEY:
                    await checks.check_deepgram(
                        candidate.deepgram.base_url, value, candidate.deepgram.model
                    )
                case SecretName.ELEVENLABS_API_KEY:
                    await checks.check_elevenlabs(value, check_voice())
                case SecretName.TYPESAFE_API_KEY:
                    await checks.check_typesafe(value, JEV_MODEL)
                case SecretName.PLIVO_AUTH_ID | SecretName.PLIVO_AUTH_TOKEN:
                    plivo = True
        except ProviderCheckError as error:
            raise ProviderCheckError(f"{name}: {error}") from None
    if plivo:
        credentials = candidate.plivo_credentials
        if credentials is None:
            raise ProviderCheckError("save the Plivo Auth ID and Auth token together")
        await checks.check_plivo(*credentials)


def placeholder_name(name: str) -> str:
    """The environment variable an exported secret names: LLM_API_KEY for llm_api_key, and
    TRIGGER_<NAME> for a trigger secret, so the two never share a name."""
    if name.startswith(TRIGGER_SECRET):
        return "TRIGGER_" + name.removeprefix(TRIGGER_SECRET)
    return name.upper()


def export_document(settings: AppSettings) -> str:
    """The settings as YAML: the values that differ from the defaults, and each saved secret
    as a placeholder."""
    document: dict[str, Any] = changed_values(settings)
    flat = settings.secrets.flat()
    named = {name: f"${{{placeholder_name(name)}}}" for name in flat if name in SECRET_NAMES}
    triggers = {
        name.removeprefix(TRIGGER_SECRET): f"${{{placeholder_name(name)}}}"
        for name in sorted(flat)
        if name.startswith(TRIGGER_SECRET)
    }
    if named:
        document["secrets"] = named
    if triggers:
        document["trigger_secrets"] = triggers
    body = yaml.safe_dump(document, sort_keys=False) if document else ""
    return DOCUMENT_HEADER + body


@dataclass
class Import:
    values: dict[str, Any]
    """The fields the document sets, by section."""
    secrets: dict[str, str | None]
    """Stored secret names; None removes the secret."""
    skipped: list[str] = field(default_factory=list)
    """Secrets given as ${NAME} with no value for NAME; they stay as they are."""


def parse_document(text: str, env: Mapping[str, str]) -> Import:
    """Read a YAML settings document. env holds the values of the ${NAME} placeholders the
    sender could resolve. Raises ValidationError."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ValidationError(f"the document is not valid YAML: {error}") from None
    document = {} if document is None else document
    if not isinstance(document, dict):
        raise ValidationError("the document must be a mapping of sections")
    values: dict[str, Any] = {}
    plan = Import(values=values, secrets={})
    for section, content in document.items():
        if section == "secrets":
            add_secrets(plan, mapping(content, "secrets"), env, prefix="")
        elif section == "trigger_secrets":
            add_secrets(plan, mapping(content, "trigger_secrets"), env, prefix=TRIGGER_SECRET)
        elif section in DEFAULTS:
            values[section] = mapping(content, section)
        else:
            raise ValidationError(f"{section}: no such section")
    unknown = [name for name in plan.secrets if not is_secret_name(name)]
    if unknown:
        raise ValidationError("; ".join(f"{name}: no such secret" for name in unknown))
    return plan


def add_secrets(plan: Import, given: dict[str, Any], env: Mapping[str, str], prefix: str) -> None:
    for key, value in given.items():
        name = f"{prefix}{key}"
        if value is None:
            plan.secrets[name] = None
            continue
        if not isinstance(value, str) or not 1 <= len(value) <= MAX_SECRET_CHARS:
            raise ValidationError(
                f"{name}: a secret is a string of 1 to {MAX_SECRET_CHARS} characters"
            )
        match = PLACEHOLDER.match(value)
        if match is None:
            plan.secrets[name] = value
        elif env.get(match.group(1)):
            plan.secrets[name] = env[match.group(1)]
        else:
            plan.skipped.append(f"{name} ({value})")


def mapping(content: Any, where: str) -> dict[str, Any]:
    if not isinstance(content, dict):
        raise ValidationError(f"{where}: must be a mapping")
    return {str(key): value for key, value in content.items()}


def describe_changes(before: AppSettings, after: AppSettings) -> list[str]:
    """What turns before into after, one line each, without any secret value. A key that a
    new base URL removes shows as removed."""
    old = before.model_dump(mode="json", include=set(DEFAULTS))
    new = after.model_dump(mode="json", include=set(DEFAULTS))
    lines = [
        f"{section}.{key}: {old[section][key]} -> {value}"
        for section, fields in new.items()
        for key, value in fields.items()
        if old[section][key] != value
    ]
    was, now = before.secrets.flat(), after.secrets.flat()
    for name in sorted(
        was.keys() | now.keys(), key=lambda name: (name.startswith(TRIGGER_SECRET), name)
    ):
        if name not in now:
            lines.append(f"{name}: removed")
        elif name not in was:
            lines.append(f"{name}: added")
        elif was[name] != now[name]:
            lines.append(f"{name}: replaced")
    return lines
