import pytest

from core.fact_verification import (
    FactVerificationError,
    align_fact_verification_to_content_contract,
    apply_fact_corrections,
    build_fact_verification_contract_v1,
    validate_fact_verification_contract_v1,
)


def item(index, status="verified", confidence=0.9, original="10", verified="10"):
    return {
        "scene_index": index,
        "person_name": f"Person {index}",
        "metric_label": "AWARDS",
        "original_value": original,
        "verified_value": verified,
        "unit": "awards",
        "as_of": "2026",
        "status": status,
        "confidence": confidence,
        "reason": "Independent AI consistency check",
        "knowledge_cutoff_risk": "low",
    }


def content_contract():
    return {
        "contentFormat": "ranking",
        "scenes": [
            {
                "title": "#2 Person 0",
                "factValue": "10",
                "metricValue": "10",
                "caption": "10",
                "statusText": "#2 | 10",
            },
            {
                "title": "#1 Person 1",
                "factValue": "20",
                "metricValue": "20",
                "caption": "20",
                "statusText": "#1 | 20",
            },
        ],
    }


def test_contract_counts_verified_corrected_and_rejected_items():
    contract = build_fact_verification_contract_v1(
        [item(0), item(1, status="corrected", original="9", verified="11")]
    )

    validate_fact_verification_contract_v1(contract)
    assert contract["status"] == "ai_verified"
    assert contract["verified_count"] == 1
    assert contract["corrected_count"] == 1


@pytest.mark.parametrize("status,confidence", [("rejected", 0.95), ("verified", 0.79)])
def test_contract_blocks_rejected_or_low_confidence_item(status, confidence):
    contract = build_fact_verification_contract_v1(
        [item(0, status=status, confidence=confidence)]
    )

    with pytest.raises(FactVerificationError):
        validate_fact_verification_contract_v1(contract, require_ai_verified=True)


def test_corrections_update_values_and_rerank_numeric_ranking():
    verification = build_fact_verification_contract_v1(
        [
            item(0, status="corrected", original="10", verified="30"),
            item(1, status="verified", original="20", verified="20"),
        ]
    )

    corrected = apply_fact_corrections(content_contract(), verification)

    assert corrected["scenes"][0]["factValue"] == "20"
    assert corrected["scenes"][1]["factValue"] == "30"
    assert corrected["scenes"][1]["title"].startswith("#1 ")


def test_align_fact_verification_matches_corrected_scene_order():
    verification = build_fact_verification_contract_v1(
        [
            item(0, status="corrected", original="10", verified="30"),
            item(1, status="verified", original="20", verified="20"),
        ]
    )
    corrected = apply_fact_corrections(content_contract(), verification)

    aligned = align_fact_verification_to_content_contract(verification, corrected)

    assert [item["verified_value"] for item in aligned["items"]] == ["20", "30"]
    assert [item["scene_index"] for item in aligned["items"]] == [0, 1]
    validate_fact_verification_contract_v1(aligned, require_ai_verified=True)
