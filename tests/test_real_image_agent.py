from agents.real_image_agent import RealImageAgent


def test_extract_person_name_from_ranked_scene_title():
    assert RealImageAgent.extract_person_name("#10 Celine Dion") == "Celine Dion"
    assert RealImageAgent.extract_person_name("#1 Jay-Z") == "Jay-Z"


def test_is_allowed_license_accepts_commons_friendly_licenses():
    assert RealImageAgent.is_allowed_license("CC BY-SA 4.0") is True
    assert RealImageAgent.is_allowed_license("Creative Commons Attribution 2.0") is True
    assert RealImageAgent.is_allowed_license("Public domain") is True
    assert RealImageAgent.is_allowed_license("All rights reserved") is False


def test_metadata_matches_person_requires_strong_name_tokens():
    metadata = "File:Celine Dion 2012.jpg Celine Dion performing live"

    assert RealImageAgent.metadata_matches_person("Celine Dion", metadata) is True
    assert RealImageAgent.metadata_matches_person("Beyonce", metadata) is False


def test_build_missing_item_contains_reviewable_reason():
    item = RealImageAgent.build_missing_item(
        scene_index=0,
        person_name="Celine Dion",
        expected_title="#10 Celine Dion",
        reason="no verified Wikimedia image found",
    )

    assert item["status"] == "missing_image"
    assert item["confidence"] == 0.0
    assert item["reject_reason"] == "no verified Wikimedia image found"
