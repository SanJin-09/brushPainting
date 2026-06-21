@echo off
REM e2e.bat — Windows 一键启动环境 + 运行 Playwright E2E 认证测试
setlocal enabledelayedexpansion

set "ROOT=%~dp0.."
cd /d "%ROOT%"

REM ---------- 测试配置 ----------
set API_AUTH_MODE=api_key
set BRUSH_API_KEYS=e2e-test-key-32-chars-minimum-xyz
set API_SESSION_SECRET=e2e-session-secret-32-chars-xyzw
set API_PUBLISH_HOST=127.0.0.1
set ALLOWED_ORIGINS=http://127.0.0.1:5173
set ALLOWED_HOSTS=localhost,127.0.0.1,::1,testserver
set APP_ENV=development
set MODEL_BACKEND=mock
set SAM3_BACKEND=mock

if "%API_PORT%"=="" set API_PORT=8000

REM ---------- 激活虚拟环境 ----------
if exist "%ROOT%\.venv\Scripts\activate.bat" (
    echo ^>^>^ 激活虚拟环境...
    call "%ROOT%\.venv\Scripts\activate.bat"
) else (
    echo [警告] 未找到 .venv，使用系统 Python
)

REM ---------- 启动 API ----------
echo ^>^>^ 启动 API ^(端口 %API_PORT%, %API_AUTH_MODE% 模式^)...
start "" /b python -m uvicorn services.api.app.main:app --host 127.0.0.1 --port %API_PORT% --reload

REM 等待 API 就绪
echo ^>^>^ 等待 API 就绪...
set READY=0
for /l %%i in (1,1,30) do (
    if !READY! equ 0 (
        timeout /t 1 /nobreak >nul
        curl -s http://127.0.0.1:%API_PORT%/healthz >nul 2>&1
        if !errorlevel! equ 0 (
            set READY=1
            echo ^>^>^ API 已就绪
        )
    )
)
if !READY! equ 0 (
    echo [错误] API 启动超时
    exit /b 1
)

REM ---------- 运行 E2E ----------
echo ^>^>^ 运行 Playwright E2E...
cd /d "%ROOT%\apps\web"
set "VITE_API_BASE=http://127.0.0.1:%API_PORT%/api"
npx playwright test %*
set EXIT_CODE=!errorlevel!

echo.
if !EXIT_CODE! equ 0 (
    echo ========== ✓ E2E 全部通过 ==========
) else (
    echo ========== ✗ E2E 存在失败 ==========
)

exit /b !EXIT_CODE!
