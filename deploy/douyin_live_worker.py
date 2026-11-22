import logging

from fastapi import FastAPI, Path

from douyin_live_page import read_desktop_live_urls


# Private Unix socket only. This worker accepts a work ID, never a URL or cookie.
logging.basicConfig(level=logging.INFO)
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/live/{work_id}")
async def live_urls(work_id: str = Path(pattern=r"^[0-9]{1,22}$")) -> dict[str, str]:
    return await read_desktop_live_urls(work_id)
