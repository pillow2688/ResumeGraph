from sqlalchemy import Boolean, CheckConstraint, DateTime, SmallInteger, String, Uuid

from app import models


def test_public_demo_config_is_a_database_enforced_singleton() -> None:
    table = models.PublicDemoConfig.__table__

    assert table.name == "public_demo_config"
    assert set(table.columns.keys()) == {
        "id",
        "candidate_name",
        "default_access_grant_id",
        "enabled",
        "created_at",
        "updated_at",
    }
    assert isinstance(table.c.id.type, SmallInteger)
    assert table.c.id.primary_key is True
    assert str(table.c.id.server_default.arg) == "1"
    assert {
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    } == {"id = 1"}


def test_public_demo_config_fields_and_access_grant_foreign_key_are_bounded() -> None:
    table = models.PublicDemoConfig.__table__

    assert isinstance(table.c.candidate_name.type, String)
    assert table.c.candidate_name.type.length == 200
    assert table.c.candidate_name.nullable is False
    assert isinstance(table.c.default_access_grant_id.type, Uuid)
    assert table.c.default_access_grant_id.nullable is False
    foreign_key = next(iter(table.c.default_access_grant_id.foreign_keys))
    assert foreign_key.target_fullname == "access_grants.id"
    assert foreign_key.ondelete is None
    assert isinstance(table.c.enabled.type, Boolean)
    assert table.c.enabled.nullable is False
    assert table.c.enabled.server_default is not None
    for name in ("created_at", "updated_at"):
        column = table.c[name]
        assert isinstance(column.type, DateTime)
        assert column.type.timezone is True
        assert column.server_default is not None
    assert table.c.updated_at.onupdate is not None
