from app.adapters.worldnewsapi_news_adapter import WorldNewsAPITopNewsAdapter
from app.pipelines.ingest import ingest_documents


class _DummyResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_fetch_calls_top_news_endpoint(monkeypatch):
    captured = {}

    def fake_get(url, params, timeout, follow_redirects):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        captured["follow_redirects"] = follow_redirects
        return _DummyResponse({"top_news": [], "country": "us", "language": "en"})

    monkeypatch.setattr("app.adapters.worldnewsapi_news_adapter.httpx.get", fake_get)

    adapter = WorldNewsAPITopNewsAdapter(
        api_key="test-key",
        source_country="us",
        language="en",
        headlines_only=True,
        timeout_seconds=12.5,
        request_date="2024-05-29",
    )

    raw = adapter.fetch()

    assert captured["url"] == "https://api.worldnewsapi.com/top-news"
    assert captured["params"] == {
        "api-key": "test-key",
        "source-country": "us",
        "language": "en",
        "date": "2024-05-29",
        "headlines-only": "true",
    }
    assert captured["timeout"] == 12.5
    assert captured["follow_redirects"] is True
    assert raw == [
        {
            "payload": {"top_news": [], "country": "us", "language": "en"},
            "request_date": "2024-05-29",
        }
    ]


def test_parse_flattens_clusters_and_preserves_metadata():
    adapter = WorldNewsAPITopNewsAdapter(api_key="test-key", request_date="2024-05-29")
    raw = [
        {
            "request_date": "2024-05-29",
            "payload": {
                "country": "us",
                "language": "en",
                "top_news": [
                    {
                        "news": [
                            {
                                "id": 1001,
                                "title": "Apple leads market rally",
                                "text": "Apple shares rose after strong results.",
                                "summary": "Apple shares rose.",
                                "url": "https://example.com/apple",
                                "publish_date": "2024-05-29 10:00:00",
                                "authors": ["Jane Doe"],
                                "image": "https://example.com/apple.jpg",
                                "video": None,
                            },
                            {
                                "id": 1002,
                                "title": "Tencent follows broader tech gains",
                                "summary": "Tencent advanced in Hong Kong trading.",
                                "url": "https://example.com/tencent",
                                "publish_date": "2024-05-29 10:05:00",
                                "author": "John Doe",
                                "authors": ["John Doe"],
                            },
                        ]
                    },
                    {
                        "news": [
                            {
                                "id": 1003,
                                "title": "Moutai demand remains resilient",
                                "text": "Demand remained resilient in the premium liquor segment.",
                                "url": "https://example.com/moutai",
                                "publish_date": "2024-05-29 10:10:00",
                                "authors": [],
                            }
                        ]
                    },
                ],
            },
        }
    ]

    docs = adapter.parse(raw)

    assert len(docs) == 3
    assert docs[0].author == "Jane Doe"
    assert docs[0].raw_text == "Apple shares rose after strong results."
    assert docs[0].metadata["worldnewsapi_article_id"] == 1001
    assert docs[0].metadata["cluster_index"] == 1
    assert docs[0].metadata["cluster_size"] == 2
    assert docs[0].metadata["request_date"] == "2024-05-29"

    assert docs[1].author == "John Doe"
    assert docs[1].raw_text == "Tencent advanced in Hong Kong trading."
    assert docs[1].metadata["cluster_index"] == 1

    assert docs[2].author is None
    assert docs[2].metadata["cluster_index"] == 2
    assert docs[2].metadata["cluster_size"] == 1


def test_ingest_skips_duplicate_top_news_across_runs(session):
    payload = {
        "country": "us",
        "language": "en",
        "top_news": [
            {
                "news": [
                    {
                        "id": 2001,
                        "title": "Apple leads market rally",
                        "text": "Apple shares rose after strong results.",
                        "url": "https://example.com/apple",
                        "publish_date": "2024-05-29 10:00:00",
                        "authors": ["Jane Doe"],
                    }
                ]
            }
        ],
    }

    class StaticWorldNewsAdapter(WorldNewsAPITopNewsAdapter):
        def fetch(self):
            return [{"payload": payload, "request_date": self.request_date}]

    first_adapter = StaticWorldNewsAdapter(api_key="test-key", request_date="2024-05-29")
    second_adapter = StaticWorldNewsAdapter(api_key="test-key", request_date="2024-05-29")

    first_saved = ingest_documents(first_adapter, session)
    second_saved = ingest_documents(second_adapter, session)

    assert len(first_saved) == 1
    assert len(second_saved) == 0
