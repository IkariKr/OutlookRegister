<script setup>
import { onMounted, onUnmounted, reactive, ref } from "vue";

const config = ref(null);
const status = ref({ running: false, pid: null, mode: null, startedAt: null, exitCode: null, lastError: null });
const logs = ref([]);
const loading = ref(false);
const saving = ref(false);
const actionLoading = ref(false);
const message = ref("");
const messageType = ref("info");

const form = reactive({
  chooseBrowser: "patchright",
  proxy: "",
  concurrentFlows: 1,
  maxTasks: 1,
  botProtectionWait: 11,
  maxCaptchaRetries: 2,
  noSystemProxy: false,
  browserPath: "",
  oauthEnabled: true,
  clientId: "",
  redirectUrl: "http://localhost:8000",
  scopesText: "offline_access\nhttps://graph.microsoft.com/Mail.ReadWrite\nhttps://graph.microsoft.com/Mail.Send\nhttps://graph.microsoft.com/User.Read",
  manualEnabled: false,
  manualTimeoutSeconds: 900,
  manualPollIntervalSeconds: 2,
  poolEnableAutoRotate: true,
  poolApiUrl: "http://127.0.0.1:5010/get/?type=https",
  poolDeleteApiUrl: "http://127.0.0.1:5010/delete/",
  poolMaxProxyRetries: 8,
  poolFetchRetriesPerRound: 6,
  poolProbeEnabled: true
});

const runOptions = reactive({
  autoTaskCount: 6,
  autoConcurrency: 3,
  autoBrowser: "patchright",
  autoProxyType: "https",
  autoMaxProxyRetries: 8,
  autoFetchProxyRetries: 6,
  autoFetchProxyRetryIntervalSeconds: 2,
  autoDisableProbe: false,
  manualTaskCount: 1,
  manualTimeoutSeconds: 900,
  manualSkipPoolProxy: true,
  manualNoSystemProxy: true
});

let timer = null;

function setMessage(text, type = "info") {
  message.value = text;
  messageType.value = type;
}

async function apiGet(url) {
  const res = await fetch(url);
  const data = await res.json();
  if (!res.ok || data.ok === false) {
    throw new Error(data.message || "请求失败");
  }
  return data;
}

async function apiPost(url, payload = {}) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const data = await res.json();
  if (!res.ok || data.ok === false) {
    throw new Error(data.message || "请求失败");
  }
  return data;
}

function ensureConfigShape(cfg) {
  if (!cfg.oauth2) cfg.oauth2 = {};
  if (!cfg.playwright) cfg.playwright = {};
  if (!cfg.manual_captcha) cfg.manual_captcha = {};
  if (!cfg.proxy_pool) cfg.proxy_pool = {};
  if (!Array.isArray(cfg.oauth2.Scopes)) cfg.oauth2.Scopes = [];
  return cfg;
}

function hydrateForm(cfg) {
  const c = ensureConfigShape(cfg);
  form.chooseBrowser = c.choose_browser ?? "patchright";
  form.proxy = c.proxy ?? "";
  form.concurrentFlows = Number(c.concurrent_flows ?? 1);
  form.maxTasks = Number(c.max_tasks ?? 1);
  form.botProtectionWait = Number(c.bot_protection_wait ?? 11);
  form.maxCaptchaRetries = Number(c.max_captcha_retries ?? 2);
  form.noSystemProxy = Boolean(c.playwright.no_system_proxy ?? false);
  form.browserPath = c.playwright.browser_path ?? "";
  form.oauthEnabled = Boolean(c.oauth2.enable_oauth2 ?? true);
  form.clientId = c.oauth2.client_id ?? "";
  form.redirectUrl = c.oauth2.redirect_url ?? "http://localhost:8000";
  form.scopesText = (c.oauth2.Scopes || []).join("\n");
  form.manualEnabled = Boolean(c.manual_captcha.enabled ?? false);
  form.manualTimeoutSeconds = Number(c.manual_captcha.timeout_seconds ?? 900);
  form.manualPollIntervalSeconds = Number(c.manual_captcha.poll_interval_seconds ?? 2);
  form.poolEnableAutoRotate = Boolean(c.proxy_pool.enable_auto_rotate ?? true);
  form.poolApiUrl = c.proxy_pool.api_url ?? "http://127.0.0.1:5010/get/?type=https";
  form.poolDeleteApiUrl = c.proxy_pool.delete_api_url ?? "http://127.0.0.1:5010/delete/";
  form.poolMaxProxyRetries = Number(c.proxy_pool.max_proxy_retries ?? 8);
  form.poolFetchRetriesPerRound = Number(c.proxy_pool.fetch_retries_per_round ?? 6);
  form.poolProbeEnabled = Boolean(c.proxy_pool.enable_probe_before_switch ?? true);
}

function applyFormToConfig(cfg) {
  const c = ensureConfigShape(structuredClone(cfg));
  c.choose_browser = form.chooseBrowser;
  c.proxy = form.proxy;
  c.concurrent_flows = Number(form.concurrentFlows);
  c.max_tasks = Number(form.maxTasks);
  c.bot_protection_wait = Number(form.botProtectionWait);
  c.max_captcha_retries = Number(form.maxCaptchaRetries);

  c.playwright.no_system_proxy = Boolean(form.noSystemProxy);
  c.playwright.browser_path = form.browserPath;

  c.oauth2.enable_oauth2 = Boolean(form.oauthEnabled);
  c.oauth2.client_id = form.clientId;
  c.oauth2.redirect_url = form.redirectUrl;
  c.oauth2.Scopes = form.scopesText
    .split("\n")
    .map((x) => x.trim())
    .filter((x) => x.length > 0);

  c.manual_captcha.enabled = Boolean(form.manualEnabled);
  c.manual_captcha.timeout_seconds = Number(form.manualTimeoutSeconds);
  c.manual_captcha.poll_interval_seconds = Number(form.manualPollIntervalSeconds);

  c.proxy_pool.enable_auto_rotate = Boolean(form.poolEnableAutoRotate);
  c.proxy_pool.api_url = form.poolApiUrl;
  c.proxy_pool.delete_api_url = form.poolDeleteApiUrl;
  c.proxy_pool.max_proxy_retries = Number(form.poolMaxProxyRetries);
  c.proxy_pool.fetch_retries_per_round = Number(form.poolFetchRetriesPerRound);
  c.proxy_pool.enable_probe_before_switch = Boolean(form.poolProbeEnabled);
  return c;
}

async function refreshStatusAndLogs() {
  try {
    const [statusResp, logsResp] = await Promise.all([apiGet("/api/status"), apiGet("/api/logs?tail=220")]);
    status.value = statusResp;
    logs.value = logsResp.lines || [];
  } catch (err) {
    setMessage(String(err.message || err), "error");
  }
}

async function loadConfig() {
  loading.value = true;
  try {
    const cfg = await apiGet("/api/config");
    config.value = ensureConfigShape(cfg);
    hydrateForm(config.value);
    setMessage("配置已加载。", "success");
  } catch (err) {
    setMessage(String(err.message || err), "error");
  } finally {
    loading.value = false;
  }
}

async function saveConfig() {
  if (!config.value) return;
  saving.value = true;
  try {
    const nextCfg = applyFormToConfig(config.value);
    await apiPost("/api/config", nextCfg);
    config.value = nextCfg;
    setMessage("配置保存成功。", "success");
  } catch (err) {
    setMessage(String(err.message || err), "error");
  } finally {
    saving.value = false;
  }
}

async function runMain() {
  actionLoading.value = true;
  try {
    await saveConfig();
    await apiPost("/api/run/main", { mode: "main" });
    setMessage("已启动 main.py。", "success");
    await refreshStatusAndLogs();
  } catch (err) {
    setMessage(String(err.message || err), "error");
  } finally {
    actionLoading.value = false;
  }
}

async function runAutoOauth2Pool() {
  actionLoading.value = true;
  try {
    await saveConfig();
    await apiPost("/api/run/auto-oauth2-pool", {
      taskCount: Number(runOptions.autoTaskCount),
      concurrency: Number(runOptions.autoConcurrency),
      browser: runOptions.autoBrowser,
      proxyType: runOptions.autoProxyType,
      maxProxyRetries: Number(runOptions.autoMaxProxyRetries),
      fetchProxyRetries: Number(runOptions.autoFetchProxyRetries),
      fetchProxyRetryIntervalSeconds: Number(runOptions.autoFetchProxyRetryIntervalSeconds),
      disableProbe: Boolean(runOptions.autoDisableProbe)
    });
    setMessage("已启动 代理池 + 自动 OAuth2 脚本。", "success");
    await refreshStatusAndLogs();
  } catch (err) {
    setMessage(String(err.message || err), "error");
  } finally {
    actionLoading.value = false;
  }
}

async function runManualMode() {
  actionLoading.value = true;
  try {
    await saveConfig();
    await apiPost("/api/run/manual", {
      taskCount: Number(runOptions.manualTaskCount),
      manualTimeoutSeconds: Number(runOptions.manualTimeoutSeconds),
      skipPoolProxy: Boolean(runOptions.manualSkipPoolProxy),
      noSystemProxy: Boolean(runOptions.manualNoSystemProxy)
    });
    setMessage("已启动人工模式脚本。", "success");
    await refreshStatusAndLogs();
  } catch (err) {
    setMessage(String(err.message || err), "error");
  } finally {
    actionLoading.value = false;
  }
}

async function stopRun() {
  actionLoading.value = true;
  try {
    await apiPost("/api/stop");
    setMessage("已发送停止请求。", "success");
    await refreshStatusAndLogs();
  } catch (err) {
    setMessage(String(err.message || err), "error");
  } finally {
    actionLoading.value = false;
  }
}

onMounted(async () => {
  await loadConfig();
  await refreshStatusAndLogs();
  timer = setInterval(() => {
    refreshStatusAndLogs();
  }, 2000);
});

onUnmounted(() => {
  if (timer) {
    clearInterval(timer);
    timer = null;
  }
});
</script>

<template>
  <div class="page">
    <header class="topbar">
      <h1>OutlookRegister 参数管理与启动面板</h1>
      <div class="status">
        <span class="badge" :class="status.running ? 'running' : 'idle'">
          {{ status.running ? "运行中" : "空闲" }}
        </span>
        <span>PID: {{ status.pid ?? "-" }}</span>
        <span>模式: {{ status.mode ?? "-" }}</span>
      </div>
    </header>

    <main class="layout">
      <section class="card form">
        <h2>参数管理</h2>
        <div class="grid">
          <label>浏览器
            <select v-model="form.chooseBrowser">
              <option value="patchright">patchright</option>
              <option value="playwright">playwright</option>
            </select>
          </label>
          <label>代理
            <input v-model="form.proxy" placeholder="例如: http://127.0.0.1:8080" />
          </label>
          <label>并发数
            <input v-model.number="form.concurrentFlows" type="number" min="1" />
          </label>
          <label>任务数
            <input v-model.number="form.maxTasks" type="number" min="1" />
          </label>
          <label>机器人等待秒数
            <input v-model.number="form.botProtectionWait" type="number" min="1" />
          </label>
          <label>验证码重试次数
            <input v-model.number="form.maxCaptchaRetries" type="number" min="0" />
          </label>
          <label>本机浏览器路径
            <input v-model="form.browserPath" placeholder="playwright 模式需要" />
          </label>
          <label class="check">
            <input v-model="form.noSystemProxy" type="checkbox" />
            无系统代理（--no-proxy-server）
          </label>
          <label class="check">
            <input v-model="form.oauthEnabled" type="checkbox" />
            启用 OAuth2
          </label>
          <label>OAuth2 client_id
            <input v-model="form.clientId" placeholder="GUID" />
          </label>
          <label>OAuth2 redirect_url
            <input v-model="form.redirectUrl" />
          </label>
          <label>代理池 API
            <input v-model="form.poolApiUrl" />
          </label>
          <label>代理池 delete API
            <input v-model="form.poolDeleteApiUrl" />
          </label>
          <label>代理池最大重试
            <input v-model.number="form.poolMaxProxyRetries" type="number" min="0" />
          </label>
          <label>每轮拉代理重试次数
            <input v-model.number="form.poolFetchRetriesPerRound" type="number" min="1" />
          </label>
          <label class="check">
            <input v-model="form.poolEnableAutoRotate" type="checkbox" />
            启用代理自动轮换
          </label>
          <label class="check">
            <input v-model="form.poolProbeEnabled" type="checkbox" />
            切换前做可用性探测
          </label>
          <label class="check">
            <input v-model="form.manualEnabled" type="checkbox" />
            启用人工验证码模式
          </label>
          <label>人工模式超时秒数
            <input v-model.number="form.manualTimeoutSeconds" type="number" min="30" />
          </label>
          <label>人工模式轮询秒数
            <input v-model.number="form.manualPollIntervalSeconds" type="number" min="1" />
          </label>
        </div>

        <label class="full">
          OAuth2 Scopes（每行一个）
          <textarea v-model="form.scopesText" rows="5"></textarea>
        </label>

        <div class="actions">
          <button :disabled="saving" @click="saveConfig">保存配置</button>
          <button :disabled="loading" @click="loadConfig">重新加载</button>
        </div>
      </section>

      <section class="card runs">
        <h2>启动控制</h2>

        <div class="run-box">
          <h3>一键自动模式（代理池 + OAuth2）</h3>
          <div class="grid small">
            <label>任务数
              <input v-model.number="runOptions.autoTaskCount" type="number" min="1" />
            </label>
            <label>并发
              <input v-model.number="runOptions.autoConcurrency" type="number" min="1" />
            </label>
            <label>浏览器
              <select v-model="runOptions.autoBrowser">
                <option value="patchright">patchright</option>
                <option value="playwright">playwright</option>
              </select>
            </label>
            <label>代理类型
              <select v-model="runOptions.autoProxyType">
                <option value="https">https</option>
                <option value="socks5">socks5</option>
              </select>
            </label>
            <label>最大代理重试
              <input v-model.number="runOptions.autoMaxProxyRetries" type="number" min="0" />
            </label>
            <label>取代理重试次数
              <input v-model.number="runOptions.autoFetchProxyRetries" type="number" min="1" />
            </label>
            <label>取代理重试间隔秒
              <input v-model.number="runOptions.autoFetchProxyRetryIntervalSeconds" type="number" min="1" />
            </label>
            <label class="check">
              <input v-model="runOptions.autoDisableProbe" type="checkbox" />
              禁用探测（不建议）
            </label>
          </div>
          <button :disabled="actionLoading" @click="runAutoOauth2Pool">启动自动模式</button>
        </div>

        <div class="run-box">
          <h3>人工模式</h3>
          <div class="grid small">
            <label>任务数
              <input v-model.number="runOptions.manualTaskCount" type="number" min="1" />
            </label>
            <label>人工超时秒数
              <input v-model.number="runOptions.manualTimeoutSeconds" type="number" min="60" />
            </label>
            <label class="check">
              <input v-model="runOptions.manualSkipPoolProxy" type="checkbox" />
              不从代理池取初始代理
            </label>
            <label class="check">
              <input v-model="runOptions.manualNoSystemProxy" type="checkbox" />
              无系统代理
            </label>
          </div>
          <button :disabled="actionLoading" @click="runManualMode">启动人工模式</button>
        </div>

        <div class="run-box">
          <h3>直接运行 main.py</h3>
          <div class="actions">
            <button :disabled="actionLoading" @click="runMain">启动 main.py</button>
            <button class="danger" :disabled="actionLoading" @click="stopRun">停止当前任务</button>
          </div>
        </div>
      </section>

      <section class="card logs">
        <h2>运行日志</h2>
        <div class="message" :class="messageType">{{ message }}</div>
        <pre>{{ logs.join("\n") }}</pre>
      </section>
    </main>
  </div>
</template>
