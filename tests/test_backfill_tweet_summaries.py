from bullet_in.backfill_tweet_summaries import targets


def test_targets_only_bodyless_tweets_that_still_have_a_summary():
    rows = [
        # 본문 없는 트윗 + 요약 있음 → 비운다
        {"content_hash": "bare", "source_id": "x_afcstuff", "body_source": None,
         "body_excerpt": None, "summary_ko": "요약", "summary3_ko": "a\nb\nc"},
        # 이미 비어 있음 → 멱등 (다시 안 잡는다)
        {"content_hash": "done", "source_id": "x_afcstuff", "body_source": None,
         "body_excerpt": None, "summary_ko": None, "summary3_ko": None},
        # 본문이 붙은 트윗 → 요약할 재료가 있으므로 그대로 둔다
        {"content_hash": "quoted", "source_id": "x_afcstuff",
         "body_source": "인용 트윗 본문", "body_excerpt": None,
         "summary_ko": "요약", "summary3_ko": "a"},
        # 트윗이 아닌 소스 → 대상 아님
        {"content_hash": "article", "source_id": "bbc_sport", "body_source": None,
         "body_excerpt": "발췌", "summary_ko": "요약", "summary3_ko": "a"},
    ]
    assert [r["content_hash"] for r in targets(rows)] == ["bare"]


def test_targets_treats_whitespace_only_summary_as_already_empty():
    rows = [{"content_hash": "ws", "source_id": "x_ornstein", "body_source": "",
             "body_excerpt": "", "summary_ko": "   ", "summary3_ko": "\n"}]
    assert targets(rows) == []
