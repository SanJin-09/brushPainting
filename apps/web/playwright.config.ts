import { defineConfig } from "@playwright/test";
import path from "path";
import os from "os";

// 复用已下载的 Chromium，避免再下 headless shell
const chromiumExe = path.join(
  os.homedir(),
  "AppData", "Local", "ms-playwright",
  "chromium-1228", "chrome-win64", "chrome.exe",
);

export default defineConfig({
  testDir: "./e2e",
  timeout: 30000,
  retries: 0,
  use: {
    // 用 127.0.0.1 而非 localhost，与 API 同 IP → SameSite=Strict cookie 正常发送
    baseURL: "http://127.0.0.1:5173",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    launchOptions: {
      executablePath: chromiumExe,
    },
  },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: true,
    timeout: 30000,
  },
});
