"""Source appendix retains historical changes while avoiding duplicate source bodies."""

from app.exports.engineering_report_text import source_appendix


def test_source_appendix_keeps_changed_current_values_and_missing_sources() -> None:
    old = {"metric": "original-reading-0", "value": 0}
    changed = {"metric": "current-reading-20.8", "value": 20.8}
    reference = {"id": "synthetic-source", "relationship": "original-citation"}
    text = source_appendix(
        {
            "versions": [{"version": n, "sources": [{**reference, "value": old}]} for n in (1, 2)],
            "latest_sources": [{**reference, "current_value": changed, "current": False}],
            "latest_source_gaps": ["synthetic-source"],
            "published_sources": [{**reference, "current_value": None, "current": False}],
            "published_source_gaps": ["synthetic-source"],
        }
    )
    assert text.count("original-reading-0") == 1
    assert text.count("current-reading-20.8") == 1
    assert text.count("original-citation") == 4
    assert '"value": 0' in text
    assert '"value_原值编号": 1' in text
    assert '"current_value_原值编号": 2' in text
    assert '"current_value_原值编号": null' in text
