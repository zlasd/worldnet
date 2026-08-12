from datetime import datetime

from PIL import Image

from app.digests.image import IMAGE_WIDTH, render_digest_jpeg
from app.digests.types import DigestMessagePayload, DigestSelectedItem


def test_render_digest_jpeg_with_chinese_text(tmp_path):
    payload = DigestMessagePayload(
        title="WorldNet 重要事项日报",
        body="ignored",
        window_start=datetime(2026, 8, 11, 7, 30),
        window_end=datetime(2026, 8, 12, 7, 30),
        summary="隔夜市场与公司公告摘要。",
        items=[
            DigestSelectedItem(
                event_id="event-1",
                rank=1,
                priority="p2",
                title="油价上涨",
                summary="布伦特原油价格上涨，能源板块波动加大。",
            )
        ],
    )
    output = tmp_path / "digest.jpg"

    rendered = render_digest_jpeg(payload, output)

    assert rendered == output
    assert output.stat().st_size > 10_000
    with Image.open(output) as image:
        assert image.format == "JPEG"
        assert image.width == IMAGE_WIDTH
        assert image.height > 500
        assert image.mode == "RGB"
