"""The infrastructure as code, held to the rules the project already has.

Terraform is not run here -- validating it needs the provider downloaded, and applying it
needs credentials. What is checked is the part that can go wrong quietly: that the code
still describes the things that actually exist, and that it cannot be pointed at the one
project which must never have billing attached.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TF = ROOT / "terraform"

pytestmark = pytest.mark.skipif(not TF.exists(), reason="no terraform directory")


def _source() -> str:
    return "\n".join(p.read_text() for p in sorted(TF.glob("*.tf")))


def _code() -> str:
    """The Terraform with comments stripped.

    Prose explaining a rule is not a breach of it. An earlier version of
    `test_the_inbox_is_never_public` failed on the comment that says the bucket must
    never have `allUsers` -- a check that cannot tell an explanation from a violation is
    a check people learn to override.
    """
    out = []
    for line in _source().splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            continue
        out.append(line.split(" # ", 1)[0])
    return "\n".join(out)


def test_the_gemini_key_project_cannot_be_managed_here():
    """`gen-lang-client-0515700308` must stay billing-disabled, and the surest way to
    keep that true is for no automation to have an opinion about it.

    The guard is a variable validation in the Terraform itself; this asserts it exists,
    because a validation somebody deletes is a validation that never fires.
    """
    source = _source()
    assert 'condition     = !startswith(var.project_id, "gen-lang-client")' in source, (
        "the project_id validation that keeps the Gemini key project out of Terraform "
        "has been removed")


def test_billing_controls_are_not_in_the_code():
    """The budgets and spend caps are what stop this project spending money. Terraform
    that can edit them is Terraform that can remove them, so they stay console-only."""
    source = _code()
    for forbidden in ("google_billing_budget", "google_billing_account_iam",
                      "google_billing_subaccount"):
        assert forbidden not in source, f"{forbidden} must not be managed by Terraform"


def test_the_inbox_is_never_public():
    """Anyone who can write to the bucket can start a pipeline that spends money per
    page. Uniform access, and no allUsers anywhere."""
    source = _code()
    assert "uniform_bucket_level_access = true" in source
    assert "allUsers" not in source and "allAuthenticatedUsers" not in source


def test_the_queue_service_carries_no_model_credential():
    """The queue must stay unable to spend. Ingestion is a separate service precisely so
    the two do not share a blast radius -- if a GOOGLE_API_KEY ever appears in the queue
    block, that property is gone."""
    main = (TF / "main.tf").read_text()
    queue = main.split('resource "google_cloud_run_v2_service" "queue"', 1)
    assert len(queue) == 2, "the queue service is no longer described"
    block = queue[1].split("\n# ---", 1)[0]
    assert "GOOGLE_API_KEY" not in block, "the queue service was given a model credential"


def test_the_secret_value_is_not_in_the_code():
    """A secret in Terraform is a secret in the state file, and the state is local."""
    source = _code()
    assert "google_secret_manager_secret_version" not in source, (
        "a secret VERSION in Terraform would put the key in state; set it by hand")
    assert not re.search(r"AQ\.[A-Za-z0-9_-]{10,}", source), "an API key literal is present"


def test_every_import_targets_a_resource_that_exists_in_the_code():
    """An import block pointing at nothing is a plan that fails at the last moment."""
    imports = (TF / "imports.tf").read_text()
    source = _source()
    for target in re.findall(r"to\s*=\s*([a-z0-9_]+\.[a-z0-9_]+)", imports):
        kind, name = target.split(".", 1)
        assert re.search(rf'resource\s+"{kind}"\s+"{name}"', source), (
            f"imports.tf adopts {target}, which no resource block defines")


def test_staging_and_production_are_the_same_code():
    """A hand-built staging environment eventually differs from production, and then the
    thing you tested is not the thing you shipped."""
    source = _source()
    assert 'variable "environment"' in source
    assert 'contains(["production", "staging"], var.environment)' in source
