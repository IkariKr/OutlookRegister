import express from "express";
import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, "..");
const CONFIG_PATH = path.join(PROJECT_ROOT, "config.json");
const PYTHON_PATH = path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe");
const AUTO_SCRIPT_PATH = path.join(PROJECT_ROOT, "start-auto-oauth2-pool.ps1");
const MANUAL_SCRIPT_PATH = path.join(PROJECT_ROOT, "start-manual-verify.ps1");

const app = express();
app.use(express.json({ limit: "1mb" }));

const runState = {
  proc: null,
  mode: null,
  startedAt: null,
  exitCode: null,
  lastError: null,
  logs: []
};

function appendLog(line) {
  runState.logs.push(`[${new Date().toISOString()}] ${line}`);
  if (runState.logs.length > 3000) {
    runState.logs.splice(0, runState.logs.length - 3000);
  }
}

function safeReadConfig() {
  const raw = fs.readFileSync(CONFIG_PATH, "utf-8");
  return JSON.parse(raw);
}

function saveConfig(nextConfig) {
  const text = JSON.stringify(nextConfig, null, 4);
  fs.writeFileSync(CONFIG_PATH, text, { encoding: "utf-8" });
}

function ensureNotRunning() {
  if (runState.proc) {
    const err = new Error("已有任务在运行，请先停止。");
    err.statusCode = 409;
    throw err;
  }
}

function spawnManagedProcess(mode, cmd, args) {
  ensureNotRunning();
  appendLog(`启动模式: ${mode}`);
  appendLog(`命令: ${cmd} ${args.join(" ")}`);

  const child = spawn(cmd, args, {
    cwd: PROJECT_ROOT,
    windowsHide: false
  });

  runState.proc = child;
  runState.mode = mode;
  runState.startedAt = new Date().toISOString();
  runState.exitCode = null;
  runState.lastError = null;

  child.stdout.on("data", (buf) => {
    const text = String(buf || "").replace(/\r/g, "");
    text.split("\n").forEach((line) => {
      if (line.trim().length > 0) {
        appendLog(line);
      }
    });
  });

  child.stderr.on("data", (buf) => {
    const text = String(buf || "").replace(/\r/g, "");
    text.split("\n").forEach((line) => {
      if (line.trim().length > 0) {
        appendLog(`[stderr] ${line}`);
      }
    });
  });

  child.on("error", (err) => {
    runState.lastError = err.message;
    appendLog(`进程错误: ${err.message}`);
  });

  child.on("close", (code) => {
    runState.exitCode = code;
    appendLog(`进程结束，退出码: ${code}`);
    runState.proc = null;
    runState.mode = null;
  });
}

async function stopRunningProcess() {
  if (!runState.proc) {
    return false;
  }

  const pid = runState.proc.pid;
  await new Promise((resolve) => {
    const killer = spawn("taskkill", ["/PID", String(pid), "/T", "/F"], {
      cwd: PROJECT_ROOT,
      windowsHide: true
    });
    killer.on("close", () => resolve());
    killer.on("error", () => resolve());
  });

  appendLog(`已请求停止进程 PID=${pid}`);
  return true;
}

app.get("/api/health", (_req, res) => {
  res.json({ ok: true });
});

app.get("/api/config", (_req, res, next) => {
  try {
    res.json(safeReadConfig());
  } catch (err) {
    next(err);
  }
});

app.post("/api/config", (req, res, next) => {
  try {
    const body = req.body;
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      const err = new Error("配置格式错误，应为 JSON 对象。");
      err.statusCode = 400;
      throw err;
    }
    saveConfig(body);
    appendLog("配置已保存");
    res.json({ ok: true });
  } catch (err) {
    next(err);
  }
});

app.get("/api/status", (_req, res) => {
  res.json({
    running: Boolean(runState.proc),
    pid: runState.proc?.pid ?? null,
    mode: runState.mode,
    startedAt: runState.startedAt,
    exitCode: runState.exitCode,
    lastError: runState.lastError
  });
});

app.get("/api/logs", (req, res) => {
  const tail = Math.max(1, Math.min(1000, Number(req.query.tail ?? 300)));
  const lines = runState.logs.slice(-tail);
  res.json({ lines });
});

app.post("/api/stop", async (_req, res, next) => {
  try {
    const stopped = await stopRunningProcess();
    res.json({ ok: true, stopped });
  } catch (err) {
    next(err);
  }
});

app.post("/api/run/main", (req, res, next) => {
  try {
    if (!fs.existsSync(PYTHON_PATH)) {
      const err = new Error(`未找到 Python: ${PYTHON_PATH}`);
      err.statusCode = 500;
      throw err;
    }

    const mode = req.body?.mode || "main";
    spawnManagedProcess(mode, PYTHON_PATH, ["main.py"]);
    res.json({ ok: true });
  } catch (err) {
    next(err);
  }
});

app.post("/api/run/manual", (req, res, next) => {
  try {
    if (!fs.existsSync(MANUAL_SCRIPT_PATH)) {
      const err = new Error(`未找到脚本: ${MANUAL_SCRIPT_PATH}`);
      err.statusCode = 500;
      throw err;
    }
    const taskCount = Number(req.body?.taskCount ?? 1);
    const timeoutSeconds = Number(req.body?.manualTimeoutSeconds ?? 900);
    const skipPoolProxy = Boolean(req.body?.skipPoolProxy ?? false);
    const noSystemProxy = Boolean(req.body?.noSystemProxy ?? false);

    const psArgs = [
      "-ExecutionPolicy",
      "Bypass",
      "-File",
      MANUAL_SCRIPT_PATH,
      "-TaskCount",
      String(taskCount),
      "-ManualTimeoutSeconds",
      String(timeoutSeconds)
    ];

    if (skipPoolProxy) {
      psArgs.push("-SkipPoolProxy");
    }
    if (noSystemProxy) {
      psArgs.push("-NoSystemProxy");
    }

    spawnManagedProcess("manual", "powershell", psArgs);
    res.json({ ok: true });
  } catch (err) {
    next(err);
  }
});

app.post("/api/run/auto-oauth2-pool", (req, res, next) => {
  try {
    if (!fs.existsSync(AUTO_SCRIPT_PATH)) {
      const err = new Error(`未找到脚本: ${AUTO_SCRIPT_PATH}`);
      err.statusCode = 500;
      throw err;
    }

    const taskCount = Number(req.body?.taskCount ?? 6);
    const concurrency = Number(req.body?.concurrency ?? 3);
    const browser = String(req.body?.browser ?? "patchright");
    const proxyType = String(req.body?.proxyType ?? "https");
    const maxProxyRetries = Number(req.body?.maxProxyRetries ?? 8);
    const fetchProxyRetries = Number(req.body?.fetchProxyRetries ?? 6);
    const fetchProxyRetryIntervalSeconds = Number(req.body?.fetchProxyRetryIntervalSeconds ?? 2);
    const disableProbe = Boolean(req.body?.disableProbe ?? false);

    const psArgs = [
      "-ExecutionPolicy",
      "Bypass",
      "-File",
      AUTO_SCRIPT_PATH,
      "-TaskCount",
      String(taskCount),
      "-Concurrency",
      String(concurrency),
      "-Browser",
      browser,
      "-ProxyType",
      proxyType,
      "-MaxProxyRetries",
      String(maxProxyRetries),
      "-FetchProxyRetries",
      String(fetchProxyRetries),
      "-FetchProxyRetryIntervalSeconds",
      String(fetchProxyRetryIntervalSeconds)
    ];
    if (disableProbe) {
      psArgs.push("-DisableProbe");
    }

    spawnManagedProcess("auto-oauth2-pool", "powershell", psArgs);
    res.json({ ok: true });
  } catch (err) {
    next(err);
  }
});

app.use((err, _req, res, _next) => {
  const statusCode = Number(err.statusCode || 500);
  const message = err?.message || "服务内部错误";
  appendLog(`[api-error] ${message}`);
  res.status(statusCode).json({ ok: false, message });
});

const port = 8787;
app.listen(port, () => {
  console.log(`manager-api listening on http://127.0.0.1:${port}`);
});
