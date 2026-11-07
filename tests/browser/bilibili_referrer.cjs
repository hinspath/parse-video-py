// Run with Playwright installed and the web app running: node tests/browser/bilibili_referrer.cjs <base-url>
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

async function main() {
    const baseUrl = process.argv[2] || "http://127.0.0.1:8767";
    const browser = await chromium.launch({
        headless: true,
        ...(process.env.BROWSER_CHANNEL ? { channel: process.env.BROWSER_CHANNEL } : {}),
    });
    try {
        for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
            const context = await browser.newContext({ viewport });
            const page = await context.newPage();
            const proxyRequests = [];
            context.on("request", request => {
                if (/\/api\/(web_download|download)\?/.test(request.url())) proxyRequests.push(request.url());
            });
            await page.route("https://cdn.jsdelivr.net/**", route => route.abort());
            const renderVideo = async url => {
                const requestPromise = page.waitForRequest(request => request.url() === url);
                await page.evaluate(videoUrl => renderResult({
                    title: "Referrer policy test", video_url: videoUrl,
                    web_proxy_enabled: false, images: [],
                    download_url: "https://dl.hins.top/api/download?unused=1",
                }), url);
                return requestPromise;
            };
            await context.route("https://**/referrer-test.mp4*", route => route.fulfill({
                status: 200, contentType: "text/html", body: "CDN policy test",
            }));
            await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
            const biliUrl = "https://upos-hz-mirrorakam.akamaized.net/referrer-test.mp4";
            const preview = await renderVideo(biliUrl);
            assert.equal((await preview.allHeaders()).referer, undefined);
            assert.equal(await page.locator("#mediaReferrerPolicy").getAttribute("content"), "no-referrer");

            const navigationPromise = context.waitForEvent("request", {
                predicate: request => request.url() === biliUrl && request.isNavigationRequest(),
            });
            const popupPromise = page.waitForEvent("popup");
            await page.locator("#resultGrid .media-download").click();
            const navigation = await navigationPromise;
            assert.equal((await navigation.allHeaders()).referer, undefined);
            assert.equal((await navigation.response()).status(), 200);
            await (await popupPromise).close();

            for (const host of ["v3.douyinvod.com", "sns-v11.rednotecdn.com", "tymov2.a.kwimgs.com"]) {
                const request = await renderVideo(`https://${host}/referrer-test.mp4`);
                assert.equal((await request.allHeaders()).referer, new URL(baseUrl).origin + "/");
                assert.equal(await page.locator("#mediaReferrerPolicy").getAttribute("content"), "strict-origin-when-cross-origin");
            }
            const hostMatching = await page.evaluate(() => [
                isBilibiliMediaUrl("https://upos-sz-mirrorcos.bilivideo.com/video.mp4"),
                isBilibiliMediaUrl("https://upos-hz-mirrorakam.akamaized.net/video.mp4"),
                isBilibiliMediaUrl("https://bilivideo.com.example.org/video.mp4"),
                isBilibiliMediaUrl("https://another.akamaized.net/video.mp4"),
            ]);
            assert.deepEqual(hostMatching, [true, true, false, false]);
            assert.equal(proxyRequests.length, 0);
            console.log(JSON.stringify({ viewport, preview_and_download_no_referrer: true,
                other_platform_policy_restored: true, proxy_requests: 0 }));
            await context.close();
        }
    } finally {
        await browser.close();
    }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
