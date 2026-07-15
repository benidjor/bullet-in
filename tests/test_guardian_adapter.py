import asyncio, respx, httpx
from bullet_in.adapters.guardian_api import GuardianAdapter

def _resp(results):
    return httpx.Response(200, json={"response": {"results": results}})

@respx.mock
def test_guardian_adapter_maps_results():
    respx.get("https://content.guardianapis.com/search").mock(return_value=_resp([
        {"webTitle": "Arsenal sign X", "webUrl": "https://g.test/1",
         "webPublicationDate": "2026-05-27T09:00:00Z",
         "fields": {"trailText": "deal done", "bodyText": "full body text",
                    "thumbnail": "https://media.test/t.jpg"}}]))
    a = GuardianAdapter(source_id="guardian", api_key="k")
    items = asyncio.run(a.fetch())
    assert items[0].url == "https://g.test/1"
    assert items[0].source_type == "api"
    p = items[0].raw_payload
    assert p["title"] == "Arsenal sign X"
    assert p["published"] == "2026-05-27T09:00:00Z"
    assert p["summary"] == "deal done"
    assert p["body"] == "full body text"
    assert p["image_url"] == "https://media.test/t.jpg"

@respx.mock
def test_guardian_adapter_requests_tag_and_fields():
    route = respx.get("https://content.guardianapis.com/search").mock(
        return_value=_resp([]))
    a = GuardianAdapter(source_id="guardian", api_key="k", tag="football/arsenal")
    asyncio.run(a.fetch())
    q = route.calls.last.request.url.params
    assert q["tag"] == "football/arsenal"
    assert q["show-fields"] == "trailText,bodyText,body,thumbnail"
    assert q["page-size"] == "20"

@respx.mock
def test_guardian_adapter_title_filter_blocks_nonmatch():
    respx.get("https://content.guardianapis.com/search").mock(return_value=_resp([
        {"webTitle": "Arsenal SIGN X", "webUrl": "https://g.test/1", "fields": {}},
        {"webTitle": "Match report: dull draw", "webUrl": "https://g.test/2",
         "fields": {}}]))
    a = GuardianAdapter(source_id="guardian", api_key="k",
                        title_contains=["sign", "transfer"])
    items = asyncio.run(a.fetch())
    assert [i.url for i in items] == ["https://g.test/1"]

@respx.mock
def test_guardian_adapter_title_filter_accepts_str():
    respx.get("https://content.guardianapis.com/search").mock(return_value=_resp([
        {"webTitle": "Transfer latest", "webUrl": "https://g.test/1", "fields": {}}]))
    a = GuardianAdapter(source_id="guardian", api_key="k", title_contains="transfer")
    assert len(asyncio.run(a.fetch())) == 1

@respx.mock
def test_guardian_adapter_missing_fields_defaults():
    respx.get("https://content.guardianapis.com/search").mock(return_value=_resp([
        {"webTitle": "Arsenal sign X", "webUrl": "https://g.test/1"}]))
    a = GuardianAdapter(source_id="guardian", api_key="k")
    p = asyncio.run(a.fetch())[0].raw_payload
    assert p["summary"] == ""
    assert p["body"] == ""
    assert p["image_url"] is None

@respx.mock
def test_guardian_adapter_strips_markup_from_summary():
    respx.get("https://content.guardianapis.com/search").mock(return_value=_resp([
        {"webTitle": "Arsenal sign X", "webUrl": "https://g.test/1",
         "fields": {"trailText": "<strong>In today's Football Daily: </strong>a big deal"}}]))
    a = GuardianAdapter(source_id="guardian", api_key="k")
    p = asyncio.run(a.fetch())[0].raw_payload
    assert p["summary"] == "In today's Football Daily: a big deal"

@respx.mock
def test_guardian_adapter_extracts_body_images():
    respx.get("https://content.guardianapis.com/search").mock(return_value=_resp([
        {"webTitle": "Arsenal sign X", "webUrl": "https://guard.test/a",
         "webPublicationDate": "2026-07-15T10:00:00Z",
         "fields": {"trailText": "t", "bodyText": "plain body",
                    "body": ('<p>One.</p><figure>'
                             '<img src="https://media.test/1.jpg"></figure>'),
                    "thumbnail": "https://media.test/t.jpg"}}]))
    a = GuardianAdapter(source_id="guardian", api_key="k")
    items = asyncio.run(a.fetch())
    assert items[0].raw_payload["images"] == ["https://media.test/1.jpg"]
    assert items[0].raw_payload["body"] == "plain body"  # bodyText 경로 무변경
