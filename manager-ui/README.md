# OutlookRegister Manager UI

Vue3 + Vite 简易管理页，用于：

- 管理 `config.json` 常用参数
- 一键启动 `main.py`
- 一键启动 `start-auto-oauth2-pool.ps1`
- 一键启动 `start-manual-verify.ps1`
- 实时查看日志并停止当前任务

## 1. 安装依赖

```powershell
cd h:\OneDrive\Develop\03_Tools\CodeX\OutlookRegister\manager-ui
npm install
```

## 2. 启动后端 API

```powershell
npm run server
```

默认监听 `http://127.0.0.1:8787`。

## 3. 启动前端页面

新开一个终端：

```powershell
cd h:\OneDrive\Develop\03_Tools\CodeX\OutlookRegister\manager-ui
npm run dev
```

默认页面地址：`http://127.0.0.1:5175`

## 4. 使用流程

1. 打开页面，确认参数。
2. 点击“保存配置”。
3. 按需点击“启动自动模式 / 启动人工模式 / 启动 main.py”。
4. 在“运行日志”区域查看输出。
5. 需要中止时点“停止当前任务”。

## 一键启动脚本

```powershell
powershell -ExecutionPolicy Bypass -File .\start-manager-ui.ps1
```

可选参数：

- `-NoBrowser`：不自动打开浏览器
- `-DryRun`：只打印启动动作，不实际执行
