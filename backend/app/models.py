"""Database tables (SQLAlchemy 2)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(10), default="admin")
    active: Mapped[bool] = mapped_column(default=True)


class AuthSession(Base):
    """Signed-in admin sessions. Only the hash of the cookie token is stored."""

    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    csrf: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen: Mapped[datetime] = mapped_column(DateTime)
    ip: Mapped[str] = mapped_column(String(45), default="")
    ended_reason: Mapped[str] = mapped_column(String(20), default="")   # '' = live, 'replaced' = another sign-in took over


class Facility(Base):
    __tablename__ = "facilities"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True)
    active: Mapped[bool] = mapped_column(default=True)


class GcpRing(Base):
    __tablename__ = "gcp_rings"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    octet1: Mapped[int] = mapped_column(Integer)
    octet2: Mapped[int] = mapped_column(Integer)
    rtu_vlan: Mapped[str] = mapped_column(String(4))
    plc_vlan: Mapped[str] = mapped_column(String(4))
    active: Mapped[bool] = mapped_column(default=True)
    __table_args__ = (UniqueConstraint("octet1", "octet2", name="uq_gcp_octets"),)


class Vendor(Base):
    """A vendor rule set: every field is host = a*n + b on a network slot (A, B, M)."""

    __tablename__ = "vendors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True)
    capacity: Mapped[int] = mapped_column(Integer)
    octets: Mapped[dict] = mapped_column(JSON)      # default third octets for the first block of a new GCP
    fields: Mapped[list] = mapped_column(JSON)      # [{field, net, a, b}]
    active: Mapped[bool] = mapped_column(default=True)


class Block(Base):
    """Address block of one GCP & Ring + vendor. Exactly one block per pair is 'active'."""

    __tablename__ = "blocks"
    id: Mapped[int] = mapped_column(primary_key=True)
    gcp_id: Mapped[int] = mapped_column(ForeignKey("gcp_rings.id"))
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"))
    seq: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10))  # planned | active | retired
    octets: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    gcp: Mapped[GcpRing] = relationship(lazy="joined")
    vendor: Mapped[Vendor] = relationship(lazy="joined")
    __table_args__ = (UniqueConstraint("gcp_id", "vendor_id", "seq", name="uq_block_seq"),)


class BlockOctet(Base):
    """A third octet of a GCP & Ring belongs to at most one block, so blocks can never overlap."""

    __tablename__ = "block_octets"
    id: Mapped[int] = mapped_column(primary_key=True)
    gcp_id: Mapped[int] = mapped_column(ForeignKey("gcp_rings.id"))
    octet3: Mapped[int] = mapped_column(Integer)
    block_id: Mapped[int] = mapped_column(ForeignKey("blocks.id", ondelete="CASCADE"))
    __table_args__ = (UniqueConstraint("gcp_id", "octet3", name="uq_gcp_octet3"),)


class Record(Base):
    __tablename__ = "records"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40))
    # lower-case name for real names (unique across active + trash); NULL for placeholders, which may repeat
    name_key: Mapped[str | None] = mapped_column(String(40), unique=True, nullable=True)
    gcp_code: Mapped[str] = mapped_column(String(40), default="", index=True)
    vendor: Mapped[str] = mapped_column(String(30), default="")
    block_id: Mapped[int | None] = mapped_column(ForeignKey("blocks.id"), nullable=True)
    host_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engineer_name: Mapped[str] = mapped_column(String(40), default="")
    record_date: Mapped[str] = mapped_column(String(20), default="")
    status: Mapped[str] = mapped_column(String(10), default="active", index=True)   # active | trash
    shared_fields: Mapped[dict] = mapped_column(JSON, default=dict)                # Subnet Mask, RTU VLAN, PLC VLAN
    import_batch_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_by: Mapped[str] = mapped_column(String(40), default="")
    ips: Mapped[list[IpAssignment]] = relationship(back_populates="record", cascade="all, delete-orphan", lazy="selectin")


class IpAssignment(Base):
    __tablename__ = "ip_assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("records.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(30))
    ip: Mapped[str] = mapped_column(String(15), index=True)
    # same as ip for device fields (UNIQUE: covers active and trashed records); NULL for shared gateway/laptop IPs
    uniq_ip: Mapped[str | None] = mapped_column(String(15), unique=True, nullable=True)
    record: Mapped[Record] = relationship(back_populates="ips")
    __table_args__ = (UniqueConstraint("record_id", "field", name="uq_record_field"),)


class AuditLog(Base):
    """Append-only change log. The application never updates or deletes rows here."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, index=True)
    role: Mapped[str] = mapped_column(String(10), default="admin")
    engineer_name: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(30))
    record_name: Mapped[str] = mapped_column(String(90), default="")
    details: Mapped[str] = mapped_column(Text, default="")
    import_batch_id: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Setting(Base):
    __tablename__ = "settings"
    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), default="")
