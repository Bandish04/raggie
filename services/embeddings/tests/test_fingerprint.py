# SPDX-License-Identifier: Apache-2.0

import re

from conftest import make_settings

from raggie_embeddings.providers.fingerprint import Profile, collection_name, fingerprint


def test_legacy_local_profile_keeps_the_existing_collection(local_settings) -> None:
    profile = Profile.from_settings(local_settings)
    assert profile.provider == "local"
    assert profile.query_prefix == "query: "
    assert profile.passage_prefix == "passage: "
    # Zero migration / zero re-embed for existing installs.
    assert collection_name(profile) == "raggie_chunks_d1024"
    assert re.fullmatch(r"[0-9a-f]{8}", fingerprint(profile))


def test_fingerprint_is_stable_and_order_independent() -> None:
    a = make_settings(embeddings_request_extra_json='{"a": 1, "b": {"y": 2, "x": 1}}')
    b = make_settings(embeddings_request_extra_json='{"b": {"x": 1, "y": 2}, "a": 1}')
    assert fingerprint(Profile.from_settings(a)) == fingerprint(Profile.from_settings(b))


def test_key_and_url_changes_do_not_change_fingerprint(cloud_settings) -> None:
    rotated = cloud_settings.model_copy(
        update={
            "embeddings_upstream_api_key": "sk-rotated",
            "embeddings_upstream_base_url": "https://proxy.internal/openai/v1",
        }
    )
    assert fingerprint(Profile.from_settings(cloud_settings)) == fingerprint(
        Profile.from_settings(rotated)
    )


def test_cloud_profile_gets_fingerprinted_collection(cloud_settings) -> None:
    profile = Profile.from_settings(cloud_settings)
    fp = fingerprint(profile)
    assert profile.query_prefix == ""  # cloud: no e5 prefixes by default
    assert collection_name(profile) == f"raggie_chunks_d4_{fp}"


def test_same_dim_different_model_never_shares_a_collection() -> None:
    e5 = Profile.from_settings(make_settings())
    other = Profile.from_settings(make_settings(embeddings_model="intfloat/multilingual-e5-base"))
    assert collection_name(e5) != collection_name(other)


def test_every_profile_field_moves_the_fingerprint(local_settings) -> None:
    base = fingerprint(Profile.from_settings(local_settings))
    variants = [
        {"embeddings_provider": "openai_compatible"},
        {"embeddings_model": "other-model"},
        {"embedding_dim": 768},
        {"embeddings_query_prefix": "q: "},
        {"embeddings_passage_prefix": ""},
        {"embeddings_request_extra_json": '{"dimensions": 1024}'},
        {"embeddings_query_extra_json": '{"input_type": "query"}'},
        {"embeddings_passage_extra_json": '{"input_type": "document"}'},
    ]
    for update in variants:
        changed = local_settings.model_copy(update=update)
        assert fingerprint(Profile.from_settings(changed)) != base, update


def test_legacy_collection_requires_the_exact_legacy_profile(local_settings) -> None:
    for update in (
        {"embeddings_query_prefix": ""},
        {"embedding_dim": 768},
        {"embeddings_request_extra_json": '{"x": 1}'},
    ):
        changed = local_settings.model_copy(update=update)
        assert collection_name(Profile.from_settings(changed)) != "raggie_chunks_d1024"
