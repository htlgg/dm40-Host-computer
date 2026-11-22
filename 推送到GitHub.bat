@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 推送到 GitHub

echo ============================================
echo   DM40 Wireless  -  推送到你的 GitHub 仓库
echo ============================================
echo.
echo 先在浏览器打开 https://github.com/new
echo   仓库名随意（例如 DM40-Wireless），不要勾选任何初始化文件
echo   创建后复制仓库地址，形如：
echo   https://github.com/你的用户名/DM40-Wireless.git
echo.
set /p URL=粘贴仓库地址后回车：
if "%URL%"=="" (
    echo 没有输入地址，已退出。
    pause
    exit /b 1
)

git remote remove origin >nul 2>&1
git remote add origin "%URL%"

echo.
echo 正在推送…（首次会弹出 GitHub 登录窗口，在浏览器里授权即可）
echo.
git push -u origin main
if errorlevel 1 (
    echo.
    echo 推送失败。常见原因：
    echo   1) 仓库不是空的（先在网页上删掉里面的文件）
    echo   2) 地址复制错（要以 .git 结尾）
    echo   3) 没有完成浏览器里的授权
) else (
    echo.
    echo 推送成功！打开 %URL% 去掉 .git 就能看到仓库了。
)
echo.
pause
