"""Catalog is the source of truth for signoff checklist item identity."""

from chipcompiler.engine.signoff.catalog import (
    CATALOG_BY_ID,
    SIGNOFF_ITEM_CATALOG,
    lookup_item,
    required_item_ids,
)


def test_catalog_ids_are_unique():
    ids = [item.id for item in SIGNOFF_ITEM_CATALOG]
    assert len(ids) == len(set(ids))
    assert set(ids) == set(CATALOG_BY_ID)


def test_required_ids_include_core_quality_and_provenance():
    required = set(required_item_ids(include_post_route_lec=True))
    assert "quality.drc.clean" in required
    assert "quality.sta.setup_closed" in required
    assert "artifact.harden.gds" in required
    assert "provenance.initial.rtl" in required
    assert "flow.drc.completed" in required
    assert "flow.postroutelec.completed" in required
    assert "artifact.postroutelec.result" in required
    assert "artifact.lec.result" not in required


def test_required_ids_omit_lec_when_skipped():
    required = set(required_item_ids(include_post_route_lec=False))
    assert "flow.postroutelec.completed" not in required
    assert "artifact.postroutelec.result" not in required
    assert "quality.drc.clean" in required


def test_package_prefix_is_dynamic_catalog_slot():
    spec = lookup_item("package.harden.gcd.png")
    assert spec is not None
    assert spec.policy == "warn"
    assert spec.optional is True
    assert lookup_item("not.a.real.id") is None
