from parse_video_py.parser.base import ImgInfo
from parse_video_py.parser.douyin import DouYin


def test_live_photo_url_prefers_last_url_and_removes_watermark():
    parser = DouYin()
    image_info = {
        "video": {
            "play_addr": {
                "url_list": [
                    "https://example.com/playwm/low.mp4",
                    "https://example.com/playwm/high.mp4",
                ]
            }
        }
    }

    assert parser._get_live_photo_url(image_info) == "https://example.com/play/high.mp4"


def test_aweme_detail_api_shape_preserves_live_photo_data():
    parser = DouYin()
    detail = {
        "desc": "测试图集",
        "images": [
            {
                "url_list": [
                    "https://example.com/cover.webp",
                    "https://example.com/image.jpg",
                ],
                "video": {
                    "download_addr": {
                        "url_list": ["https://example.com/playwm/live.mp4"]
                    }
                },
            }
        ],
        "video": {
            "play_addr": {"uri": "music-uri"},
            "cover": {"url_list": ["https://example.com/cover.jpg"]},
        },
        "author": {
            "sec_uid": "uid",
            "nickname": "作者",
            "avatar_thumb": {"url_list": ["https://example.com/avatar.jpg"]},
        },
    }

    result = parser._video_info_from_aweme_detail(detail)

    assert result.video_url == ""
    assert result.music_url == "music-uri"
    assert result.title == "测试图集"
    assert result.images == [
        ImgInfo(
            url="https://example.com/image.jpg",
            live_photo_url="https://example.com/play/live.mp4",
        )
    ]
    assert result.author.name == "作者"
