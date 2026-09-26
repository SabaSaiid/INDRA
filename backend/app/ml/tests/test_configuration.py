from datetime import datetime, timezone

import pytest

from app.ml.config import (
    load_artifact_manifest,
    validate_artifact_manifest,
    validate_artifact_metadata,
)
from app.ml.contracts import ArtifactManifest, ArtifactMetadata, ArtifactPolicyStatus


def valid_artifact(**updates):
    value = {
        "artifact_name": "example",
        "artifact_version": "v1",
        "sha256": "a" * 64,
        "training_dataset_hash": "b" * 64,
        "feature_version": "features-v1",
        "preprocessing_version": "preprocess-v1",
        "training_timestamp": datetime.now(timezone.utc),
        "random_seed": 42,
        "framework_versions": {"scikit-learn": "not-installed-in-phase-1"},
        "intended_component": "nlp_classifier",
        "policy_status": ArtifactPolicyStatus.COMPLIANT,
    }
    value.update(updates)
    return ArtifactMetadata(**value)


def test_committed_scaffold_manifest_is_loadable():
    manifest = load_artifact_manifest()
    nlp_artifacts = [
        artifact for artifact in manifest.artifacts
        if artifact.intended_component == "nlp_classifier"
    ]
    assert {artifact.artifact_name for artifact in nlp_artifacts} == {
        "nlp_classifier_v1.json",
        "nlp_classifier_v2.json",
        "nlp_classifier_v3.json",
    }
    assert all(
        artifact.policy_status is ArtifactPolicyStatus.COMPLIANT
        for artifact in nlp_artifacts
    )
    duplicate_artifacts = [
        artifact
        for artifact in manifest.artifacts
        if artifact.intended_component == "duplicate_matcher"
    ]
    assert {artifact.artifact_name for artifact in duplicate_artifacts} == {
        "duplicate_feature_state.json",
        "duplicate_feature_state_v2.json",
        "duplicate_matcher_v1.json",
    }
    assert all(
        artifact.policy_status is ArtifactPolicyStatus.COMPLIANT
        for artifact in duplicate_artifacts
    )
    assert manifest.runtime_downloads_allowed is False
    assert manifest.legacy_artifacts


def test_noncompliant_artifact_cannot_be_accepted():
    metadata = valid_artifact(policy_status=ArtifactPolicyStatus.LEGACY_NON_COMPLIANT)
    with pytest.raises(ValueError, match="not policy-compliant"):
        validate_artifact_metadata(metadata)


def test_duplicate_manifest_entries_and_remote_manifests_are_rejected():
    metadata = valid_artifact()
    manifest = ArtifactManifest(
        manifest_version="1.0",
        schema_version="1.0",
        policy_status="SCAFFOLD_ONLY",
        artifacts=[metadata, metadata],
    )
    with pytest.raises(ValueError, match="duplicate component entries"):
        validate_artifact_manifest(manifest)
    with pytest.raises(ValueError, match="remote artifact manifests"):
        load_artifact_manifest("https://example.invalid/manifest.json")
