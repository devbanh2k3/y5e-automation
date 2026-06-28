def test_description_hashtags_are_appended_from_tags() -> None:
    from core.seo_metadata import ensure_description_hashtags

    result = ensure_description_hashtags(
        "Public estimates ranked for entertainment viewers.",
        ["celebrity facts", "data comparison", "net worth"],
    )

    assert "Public estimates" in result
    assert "#CelebrityFacts" in result
    assert "#DataComparison" in result
    assert "#NetWorth" in result


def test_description_hashtag_block_is_replaced_not_duplicated() -> None:
    from core.seo_metadata import ensure_description_hashtags

    result = ensure_description_hashtags("Body\n\n#OldTag", ["old tag", "new tag"])

    assert result.count("#OldTag") == 1
    assert "#NewTag" in result
