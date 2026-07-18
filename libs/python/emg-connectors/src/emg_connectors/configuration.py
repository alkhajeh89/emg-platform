"""Connector configuration schema + authentication contract (FEAT-13-1).

A connector declares a `ConnectorConfigurationSchema` (a set of typed
`ConfigField`s). A deployment supplies a `ConnectorConfiguration` (scalar values);
`ConnectorValidator` checks it against the schema. `ConnectorAuthentication`
declares *which* authentication mechanism is used and an **opaque credential
reference** — never a raw secret. The framework implements no authentication and
transmits nothing; it only models the contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from .enums import AuthenticationMechanism
from .labels import SafeLabel, SafeText, ensure_safe_label
from .limits import MAX_AUTH_MECHANISMS, MAX_CONFIG_FIELDS

# A configuration value is a JSON-style scalar only. No nested objects, no
# callables — so a configuration carries no arbitrary object or injection payload.
ScalarValue = str | int | float | bool | None


class ConfigFieldType(str, Enum):
    """The scalar type of a configuration field."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"


_PYTYPE: dict[ConfigFieldType, type | tuple[type, ...]] = {
    ConfigFieldType.STRING: str,
    ConfigFieldType.INTEGER: int,
    ConfigFieldType.FLOAT: (int, float),
    ConfigFieldType.BOOLEAN: bool,
}


def _matches(field_type: ConfigFieldType, value: ScalarValue) -> bool:
    if value is None:
        return True
    if field_type is ConfigFieldType.INTEGER and isinstance(value, bool):
        return False  # bool is a subtype of int; keep them distinct
    if field_type is not ConfigFieldType.BOOLEAN and isinstance(value, bool):
        return False
    return isinstance(value, _PYTYPE[field_type])


class ConfigField(BaseModel):
    """One typed configuration field declared by a connector's schema. A field
    marked `secret` must be supplied as an opaque *reference* (never a raw
    secret)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: SafeLabel
    type: ConfigFieldType
    required: bool = False
    secret: bool = False
    description: SafeText | None = None
    default: ScalarValue = None

    @model_validator(mode="after")
    def _validate_default(self) -> ConfigField:
        if self.default is not None and not _matches(self.type, self.default):
            raise ValueError(f"default for {self.name!r} does not match type {self.type.value}")
        if self.secret and self.type is not ConfigFieldType.STRING:
            raise ValueError("a secret field must be of type string (an opaque reference)")
        if self.secret and self.default is not None:
            raise ValueError("a secret field must not declare an inline default value")
        return self


class ConnectorConfigurationSchema(BaseModel):
    """A connector's immutable configuration schema: a set of typed fields with
    unique names, bounded in count."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fields: tuple[ConfigField, ...] = ()

    @field_validator("fields")
    @classmethod
    def _validate_fields(cls, v: tuple[ConfigField, ...]) -> tuple[ConfigField, ...]:
        if len(v) > MAX_CONFIG_FIELDS:
            raise ValueError(f"too many config fields (max {MAX_CONFIG_FIELDS})")
        names = [f.name for f in v]
        if len(names) != len(set(names)):
            raise ValueError("configuration field names must be unique")
        return v

    def field(self, name: str) -> ConfigField | None:
        for f in self.fields:
            if f.name == name:
                return f
        return None

    def required_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields if f.required)


class ConnectorConfiguration(BaseModel):
    """A deployment-supplied, immutable set of configuration values for a
    connector. Values are a read-only scalar mapping; validate against a schema
    with `ConnectorValidator.validate_configuration`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    connector_id: SafeLabel
    values: Mapping[str, ScalarValue] = Field(default_factory=dict)

    @field_validator("values")
    @classmethod
    def _freeze_values(cls, v: Mapping[str, ScalarValue]) -> Mapping[str, ScalarValue]:
        for key in v:
            if not isinstance(key, str):  # pragma: no cover - defensive
                raise ValueError("configuration keys must be strings")
            ensure_safe_label(key)
        return MappingProxyType({k: v[k] for k in sorted(v)})

    @field_serializer("values")
    def _ser_values(self, v: Mapping[str, ScalarValue]) -> dict[str, ScalarValue]:
        return dict(v)


class ConnectorAuthentication(BaseModel):
    """A connector's authentication *declaration*: which mechanism is used and an
    **opaque credential reference** (e.g. a secret-manager key). This framework
    implements no authentication and stores no secret — `credential_ref` is a
    handle a deployment resolves out-of-band."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mechanism: AuthenticationMechanism = AuthenticationMechanism.NONE
    credential_ref: SafeLabel | None = None
    scopes: tuple[SafeLabel, ...] = ()

    @model_validator(mode="after")
    def _validate(self) -> ConnectorAuthentication:
        if self.mechanism is not AuthenticationMechanism.NONE and self.credential_ref is None:
            raise ValueError(
                f"mechanism {self.mechanism.value} requires a credential_ref "
                "(an opaque reference, never a raw secret)"
            )
        if self.mechanism is AuthenticationMechanism.NONE and self.credential_ref is not None:
            raise ValueError("mechanism 'none' must not carry a credential_ref")
        if len(self.scopes) > MAX_AUTH_MECHANISMS:
            raise ValueError("too many scopes")
        return self
