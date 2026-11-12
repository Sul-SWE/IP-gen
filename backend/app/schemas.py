"""Request bodies (Pydantic). Unknown fields are rejected; lengths are capped."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

Short = Field(max_length=60)


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginIn(Body):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)
    force: bool = False


class PasswordIn(Body):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)


class GenerateIn(Body):
    facility: str = Field(max_length=8)
    well: str = Field(max_length=5)
    gcp: str = Field(max_length=40)
    vendor: str = Field(max_length=30)
    engineer: str = Field(max_length=60)


class SaveIn(GenerateIn):
    signature: str = Field(max_length=64)


class Acting(Body):
    actor: str = Field(max_length=60)
    version: int | None = None


class EditPreviewIn(Body):
    gcp: str = Field(max_length=40)
    vendor: str = Field(max_length=30)


class UpdateIn(Acting):
    name: str | None = Field(default=None, max_length=40)
    engineer: str | None = Field(default=None, max_length=60)
    date: str | None = Field(default=None, max_length=20)
    gcp: str | None = Field(default=None, max_length=40)
    vendor: str | None = Field(default=None, max_length=30)
    signature: str | None = Field(default=None, max_length=64)


class ImportConfirmIn(Body):
    token: str = Field(max_length=80)
    actor: str = Field(max_length=60)


class UndoIn(Body):
    actor: str = Field(max_length=60)
    batch: str | None = Field(default=None, max_length=40)


class FacilityIn(Body):
    code: str = Field(max_length=8)
    actor: str = Field(max_length=60)


class ActiveIn(Body):
    active: bool
    actor: str = Field(max_length=60)


class GcpIn(Body):
    code: str = Field(max_length=40)
    octet1: int = Field(ge=0, le=255)
    octet2: int = Field(ge=0, le=255)
    rtu_vlan: int = Field(ge=1, le=4094)
    plc_vlan: int = Field(ge=1, le=4094)
    actor: str = Field(max_length=60)


class GcpUpdateIn(Body):
    rtu_vlan: int | None = Field(default=None, ge=1, le=4094)
    plc_vlan: int | None = Field(default=None, ge=1, le=4094)
    active: bool | None = None
    actor: str = Field(max_length=60)


class FieldIn(Body):
    field: str = Field(max_length=30)
    net: str = Field(max_length=1)
    a: int = Field(ge=0, le=254)
    b: int = Field(ge=-254, le=254)


class VendorIn(Body):
    name: str = Field(max_length=30)
    capacity: int = Field(ge=1, le=254)
    octets: dict[str, int]
    fields: list[FieldIn] = Field(max_length=11)
    actor: str = Field(default="", max_length=60)


class BlockIn(Body):
    gcp_id: int
    vendor_id: int
    octets: dict[str, int]
    actor: str = Field(max_length=60)


class ActorIn(Body):
    actor: str = Field(max_length=60)


class SettingsIn(Body):
    warn_at: int = Field(ge=50, le=99)      # percent
    actor: str = Field(max_length=60)
