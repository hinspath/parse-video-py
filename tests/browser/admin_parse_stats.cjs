// Run against a local web server with the test admin credentials set in the environment.
const assert = require("node:assert/strict");
const { chromium } = require("playwright");

async function main() {
    const baseURL = process.argv[2] || "http://127.0.0.1:8768";
    const httpCredentials = { username: process.env.ADMIN_USERNAME, password: process.env.ADMIN_PASSWORD };
    assert.ok(httpCredentials.username && httpCredentials.password);
    const browser = await chromium.launch({
        headless: true,
        ...(process.env.BROWSER_CHANNEL ? { channel: process.env.BROWSER_CHANNEL } : {}),
    });
    try {
        for (const viewport of [{ width: 1440, height: 900 }, { width: 320, height: 800 }]) {
            const context = await browser.newContext({ baseURL, viewport, httpCredentials });
            const page = await context.newPage();
            const seen = [];
            await page.route("**/api/admin/parse_stats?*", async (route) => {
                const params = new URL(route.request().url()).searchParams;
                seen.push(Object.fromEntries(params));
                if (params.get("days") === "30") {
                    return route.fulfill({ status: 503, json: { code: 503 } });
                }
                const web = params.get("channel") === "web";
                const overall = web ? { total: 0, success: 0, failed: 0, rate: null }
                    : { total: 8, success: 7, failed: 1, rate: 87.5 };
                await route.fulfill({ json: { code: 200, data: {
                    start: "2026-11-21", end: "2026-11-22", overall,
                    platforms: web ? [] : [{ platform: "douyin", ...overall }],
                    failures: web ? [] : [{ reason: "upstream_timeout", count: 1 }],
                } } });
            });
            const response = await page.goto("/admin");
            assert.equal(response.status(), 200);
            await page.getByText("平台响应超时").waitFor();
            assert.equal(await page.locator("#parseStatsRate").textContent(), "87.5%");
            assert.ok(await page.locator("#parseStatsRate").evaluate(el => {
                const range = document.createRange();
                range.selectNodeContents(el);
                return range.getClientRects().length === 1;
            }));
            assert.ok(await page.getByRole("rowheader", { name: "抖音" }).isVisible());
            assert.ok(await page.locator("#parseStatsTable").evaluate(el => el.scrollWidth <= el.clientWidth));
            assert.ok(await page.locator(".parse-stats").evaluate(el => el.scrollWidth <= el.clientWidth));
            if (process.env.SCREENSHOT_DIR) {
                await page.screenshot({ path: `${process.env.SCREENSHOT_DIR}/admin-parse-stats-${viewport.width}.png` });
            }
            await page.locator("#parseStatsChannel").selectOption("web");
            await page.getByText("暂无解析记录", { exact: false }).waitFor();
            assert.equal(await page.locator("#parseStatsRate").textContent(), "–");
            assert.equal(await page.locator("#parseStatsTable").isVisible(), false);
            await page.locator("#parseStatsDays").selectOption("2");
            await page.getByRole("button", { name: "刷新", exact: true }).click();
            assert.ok(seen.some(query => query.channel === "web" && query.days === "2"));
            await page.locator("#parseStatsDays").selectOption("30");
            await page.getByText("统计暂不可用，请刷新重试", { exact: false }).waitFor();
            assert.ok(await page.locator("#refreshParseStatsBtn").isEnabled());
            await page.unroute("**/api/admin/parse_stats?*");
            await page.reload();
            await page.getByText("暂无解析记录", { exact: false }).waitFor();
            await context.close();
            console.log(JSON.stringify({ viewport, rendered: true, filters: true, empty: true, error: true }));
        }
    } finally {
        await browser.close();
    }
}

main().catch(error => { console.error(error); process.exitCode = 1; });
