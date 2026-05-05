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


def test_live_photo_url_finds_nested_video_url():
    parser = DouYin()
    image_info = {
        "url_list": ["https://example.com/image.jpg"],
        "video": {
            "bit_rate": [
                {
                    "play_addr": {
                        "url_list": [
                            "https://example.com/live/playwm/?video_id=abc123"
                        ]
                    }
                }
            ]
        },
    }

    assert (
        parser._get_live_photo_url(image_info)
        == "https://example.com/live/play/?video_id=abc123"
    )


def test_extract_signature_from_execjs_error_output():
    parser = DouYin()
    err_text = """(-6, '\n["ok","dJWhQRLDDE2PhD6f51/LfY3q6IN3Y8y30trEMD2fFdfZd639HMT09exoRpzvjUmjE4/0IeYjy4hbT3ohrQ2y8qwf9W0L/25gsDSkKl12so0j53inCLf/E0iE5hsAtFH8svr4iKi8owICSYyhldAJ5kIlO62-zo0/9IL="]\n', '')"""

    assert parser._extract_signature_from_text(err_text).startswith("dJWhQR")


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


def test_aweme_detail_image_post_info_preserves_live_photo_data():
    parser = DouYin()
    detail = {
        "desc": "实况图集",
        "image_post_info": {
            "images": [
                {
                    "display_image": {
                        "url_list": [
                            "https://example.com/display.webp",
                            "https://example.com/display.jpg",
                        ]
                    },
                    "video": {
                        "play_addr": {
                            "url_list": ["https://example.com/playwm/live.mp4"]
                        }
                    },
                }
            ]
        },
        "video": {"cover": {"url_list": ["https://example.com/cover.jpg"]}},
        "author": {"nickname": "作者"},
    }

    result = parser._video_info_from_aweme_detail(detail)

    assert result.images == [
        ImgInfo(
            url="https://example.com/display.jpg",
            live_photo_url="https://example.com/play/live.mp4",
        )
    ]
