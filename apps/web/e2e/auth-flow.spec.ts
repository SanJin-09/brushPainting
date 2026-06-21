import { test, expect } from "@playwright/test";

const TEST_API_KEY = "e2e-test-key-32-chars-minimum-xyz";

test.describe("认证流程", () => {
  test.beforeEach(async ({ page }) => {
    // 先清掉上一次的 session，确保每次从登录页开始
    await page.goto("/");
    await page.evaluate(() => localStorage.clear());
    await page.evaluate(() => sessionStorage.clear());
  });

  test("① 未认证访问 → 看到登录页", async ({ page }) => {
    await page.goto("/");

    // 断言：页面显示"验证访问权限"
    await expect(page.getByText("验证访问权限")).toBeVisible();

    // 断言：API Key 输入框可见
    const input = page.getByLabel("API Key");
    await expect(input).toBeVisible();
    await expect(input).toHaveAttribute("type", "password");
  });

  test("② 错误 Key → 显示错误", async ({ page }) => {
    await page.goto("/");

    // 输入错误 Key
    await page.getByLabel("API Key").fill("wrong-key");

    // 点击提交
    await page.getByRole("button", { name: "进入工作台" }).click();

    // 断言：显示错误提示
    await expect(page.getByText(/无效|拒绝/)).toBeVisible();

    // 断言：仍然停留在登录页
    await expect(page.getByText("验证访问权限")).toBeVisible();
  });

  test("③ 正确 Key → 进入工作台", async ({ page }) => {
    await page.goto("/");

    // 输入正确 Key
    await page.getByLabel("API Key").fill(TEST_API_KEY);

    // 提交
    await page.getByRole("button", { name: "进入工作台" }).click();

    // 断言：进入工作台，能看到 NavBar
    await expect(page.getByRole("heading", { name: "工笔重绘工作台" })).toBeVisible();

    // 断言：顶部显示"安全会话已启用"
    await expect(page.getByText("安全会话已启用")).toBeVisible();

    // 断言：上传按钮可见
    await expect(page.getByRole("button", { name: "上传并创建批次" })).toBeVisible();
  });

  test("④ 退出会话 → 回到登录页", async ({ page }) => {
    // 先登录
    await page.goto("/");
    await page.getByLabel("API Key").fill(TEST_API_KEY);
    await page.getByRole("button", { name: "进入工作台" }).click();
    await expect(page.getByText("安全会话已启用")).toBeVisible();

    // 点击退出
    await page.getByRole("button", { name: "退出会话" }).click();

    // 断言：回到登录页
    await expect(page.getByText("验证访问权限")).toBeVisible();

    // 断言：不再显示"安全会话已启用"
    await expect(page.getByText("安全会话已启用")).not.toBeVisible();
  });

  test("⑤ 登录后上传图片 → 缩略图正常加载（不为 401）", async ({ page }) => {
    // 登录
    await page.goto("/");
    await page.getByLabel("API Key").fill(TEST_API_KEY);
    await page.getByRole("button", { name: "进入工作台" }).click();
    await expect(page.getByText("安全会话已启用")).toBeVisible();

    // 上传一张测试图片（创建 1x1 像素 PNG）
    const fileChooserPromise = page.waitForEvent("filechooser");
    // 点击上传区域触发文件选择
    await page.locator(".upload-dropzone, .upload-add-card").first().click();
    const fileChooser = await fileChooserPromise;
    await fileChooser.setFiles({
      name: "test.png",
      mimeType: "image/png",
      buffer: Buffer.from(
        // 最小的有效 PNG (1x1 红色像素)
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==",
        "base64",
      ),
    });

    // 确认预览出现
    await expect(page.locator(".upload-preview-card, .upload-preview-img").first()).toBeVisible({
      timeout: 5000,
    });

    // 点击上传按钮
    await page.getByRole("button", { name: /上传并创建批次/ }).click();

    // 断言：跳转到批次详情页，图片缩略图加载成功
    await expect(page.locator("img[alt]").first()).toBeVisible({ timeout: 10000 });

    // 确认缩略图的 src 是通过 /media/ 受保护路由加载的
    const thumbSrc = await page.locator(".image-card img").first().getAttribute("src");
    expect(thumbSrc).toBeTruthy();
    expect(thumbSrc).toContain("/media/");
  });
});
