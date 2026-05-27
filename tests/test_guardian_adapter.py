import asyncio, respx, httpx
from bullet_in.adapters.guardian_api import GuardianAdapter

@respx.mock
def test_guardian_adapter_maps_results():
    respx.get("https://content.guardianapis.com/search").mock(
        return_value=httpx.Response(200, json={"response": {"results": [
            {"webTitle": "Arsenal sign X", "webUrl": "https://g.test/1",
             "webPublicationDate": "2026-05-27T09:00:00Z",
             "fields": {"trailText": "deal done"}}]}}))
    a = GuardianAdapter(source_id="guardian", api_key="k", query="Arsenal")
    items = asyncio.run(a.fetch())
    assert items[0].url == "https://g.test/1"
    assert items[0].raw_payload["title"] == "Arsenal sign X"
    assert items[0].source_type == "api"
