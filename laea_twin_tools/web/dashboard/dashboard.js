const $ = (id) => document.getElementById(id);
let profilesLoaded = false;

function text(id, value, fallback = "—") {
  $(id).textContent = value === undefined || value === null || value === "" ? fallback : value;
}

function number(value, digits = 2) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : "—";
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[character]);
}

function setBadge(element, label, style) {
  element.textContent = label;
  element.className = `badge ${style}`;
}

function stateClass(value) {
  return (value || "unknown").toLowerCase();
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function readConfig(collectionMode) {
  return {
    collection_mode: collectionMode,
    dataset_name: $("datasetName").value.trim(),
    scenario: $("scenario").value.trim(),
    world_name: $("worldName").value,
    attack_profile: $("attackProfile").value,
    attack_seed: Number($("attackSeed").value),
    max_duration_s: Number($("maxDuration").value),
    detector_name: $("detectorName").value.trim(),
    supervisor_policy: $("supervisorPolicy").value,
    total_rounds: Number($("totalRounds").value),
    sleep_between_rounds_s: Number($("roundInterval").value),
    increment_seed: $("incrementSeed").checked,
    enable_rtp: $("enableRtp").checked,
    enable_rviz: $("enableRviz").checked,
    enable_ditto: $("enableDitto").checked,
  };
}

async function startExperiment(collectionMode) {
  const isBatch = collectionMode === "batch";
  const prompt = isBatch
    ? `開始自動蒐集 ${$("totalRounds").value} 輪訓練資料？`
    : "啟動新的 LAEA 單次實驗？";
  if (!confirm(prompt)) return;
  try {
    $("actionMessage").textContent = isBatch ? "正在啟動自動蒐集…" : "正在啟動實驗程序…";
    await api("/api/experiment/start", {
      method: "POST",
      body: JSON.stringify(readConfig(collectionMode)),
    });
    $("actionMessage").textContent = isBatch ? "自動蒐集程序已啟動。" : "實驗程序已啟動。";
    await refreshState();
    await refreshLog();
  } catch (error) {
    $("actionMessage").textContent = `啟動失敗：${error.message}`;
  }
}

async function stopExperiment() {
  if (!confirm("停止目前實驗？這會送出 SIGINT 並清理背景程序。")) return;
  try {
    $("actionMessage").textContent = "正在停止實驗…";
    await api("/api/experiment/stop", { method: "POST", body: "{}" });
    $("actionMessage").textContent = "實驗已停止。";
    await refreshState();
    await refreshLog();
  } catch (error) {
    $("actionMessage").textContent = `停止失敗：${error.message}`;
  }
}

async function sendOverride(level) {
  if (level === "HOVER" && !confirm("送出手動 Hover override？")) return;
  try {
    await api("/api/supervisor", {
      method: "POST",
      body: JSON.stringify({ level, reason: `dashboard_manual_${level.toLowerCase()}` }),
    });
    $("actionMessage").textContent = level === "NONE" ? "已清除手動 override。" : `已送出 ${level} override。`;
  } catch (error) {
    $("actionMessage").textContent = `指令失敗：${error.message}`;
  }
}

const TREND_MAX = 180;
const trend = [];

function pushTrend(mission, attack) {
  trend.push({
    loc: Number(mission.localization_score) || 0,
    perc: Number(mission.perception_score) || 0,
    plan: Number(mission.planner_score) || 0,
    flight: Number(mission.flight_safety_score) || 0,
    attack: Boolean(attack.active),
  });
  while (trend.length > TREND_MAX) trend.shift();
}

function drawTrends() {
  const canvas = $("trendCanvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 600;
  const h = canvas.clientHeight || 220;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const pad = { l: 26, r: 8, t: 8, b: 8 };
  const plotW = w - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;
  const yMax = 3;
  const xAt = (i) => pad.l + (i / (TREND_MAX - 1)) * plotW;
  const yAt = (v) => pad.t + plotH - Math.min(Math.max(v, 0), yMax) / yMax * plotH;

  ctx.fillStyle = "rgba(255, 107, 107, .16)";
  for (let i = 0; i < trend.length; i++) {
    if (trend[i].attack) {
      const x0 = xAt(i);
      const x1 = xAt(Math.min(i + 1, TREND_MAX - 1));
      ctx.fillRect(x0, pad.t, Math.max(x1 - x0, 1.5), plotH);
    }
  }

  ctx.strokeStyle = "rgba(143, 172, 164, .5)";
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(pad.l, yAt(1));
  ctx.lineTo(pad.l + plotW, yAt(1));
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = "#8facA4";
  ctx.font = "10px sans-serif";
  [0, 1, 3].forEach((v) => ctx.fillText(String(v), 6, yAt(v) + 3));

  const series = [["loc", "#55c2d9"], ["perc", "#49d49d"], ["plan", "#f2c14e"], ["flight", "#ff6b6b"]];
  for (const [key, color] of series) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let i = 0; i < trend.length; i++) {
      const x = xAt(i);
      const y = yAt(trend[i][key]);
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.stroke();
  }
}

async function triggerAttack() {
  const profile = $("liveAttackProfile").value;
  if (!profile) return;
  if (!confirm(`立即觸發攻擊 ${profile}？`)) return;
  try {
    await api("/api/attack/trigger", { method: "POST", body: JSON.stringify({ profile }) });
    $("actionMessage").textContent = `已觸發攻擊：${profile}`;
  } catch (error) {
    $("actionMessage").textContent = `觸發失敗：${error.message}`;
  }
}

async function stopAttack() {
  try {
    await api("/api/attack/stop", { method: "POST", body: "{}" });
    $("actionMessage").textContent = "已送出停止攻擊。";
  } catch (error) {
    $("actionMessage").textContent = `停止失敗：${error.message}`;
  }
}

function renderRuns(rows) {
  const body = $("runsBody");
  if (!rows || rows.length === 0) {
    body.innerHTML = '<tr><td colspan="6">尚無 manifest 資料</td></tr>';
    return;
  }
  body.innerHTML = rows.map((row) => `
    <tr>
      <td>${escapeHtml(row.run_id || "—")}</td>
      <td>${escapeHtml(row.outcome || "—")}</td>
      <td>${number(row.duration_s, 1)} s</td>
      <td>${escapeHtml(row.scenario || "—")}</td>
      <td>${escapeHtml([row.attack_source, row.attack_mode, row.attack_severity].filter(Boolean).join(" / ") || "none")}</td>
      <td>${row.log_retained === "true" ? "kept" : row.log_deleted === "true" ? "deleted" : "none"}</td>
    </tr>`).join("");
}

function renderState(data) {
  const process = data.process || {};
  const telemetry = data.telemetry || {};
  const mavros = telemetry.mavros || {};
  const pose = telemetry.pose || {};
  const velocity = telemetry.velocity || {};
  const depth = telemetry.depth || {};
  const mission = telemetry.mission || {};
  const attack = telemetry.attack || {};
  const supervisor = telemetry.supervisor || {};
  const ages = telemetry.ages_s || {};
  const batch = process.batch_progress || {};
  const isBatch = process.collection_mode === "batch";

  setBadge($("rosBadge"), data.ros_master_online ? "ROS ONLINE" : "ROS OFFLINE", data.ros_master_online ? "good" : "bad");
  const processLabel = process.running
    ? isBatch
      ? "COLLECTING DATA"
      : "EXPERIMENT RUNNING"
    : "IDLE";
  setBadge($("processBadge"), processLabel, process.running ? "warning" : "neutral");
  $("startButton").disabled = Boolean(process.running);
  $("startBatchButton").disabled = Boolean(process.running);
  $("stopButton").disabled = !process.running;

  text("px4Connection", mavros.connected ? "CONNECTED" : "DISCONNECTED");
  text("px4Mode", mavros.mode);
  text("px4Armed", mavros.armed === undefined ? null : mavros.armed ? "ARMED" : "DISARMED");
  text("positionValue", Number.isFinite(pose.x) ? `${number(pose.x)} / ${number(pose.y)} / ${number(pose.z)} m` : null);
  text("speedValue", Number.isFinite(velocity.speed) ? `${number(velocity.speed)} m/s` : null);
  text("satellitesValue", telemetry.satellites);
  text("depthStatus", ages.depth !== undefined && ages.depth < 1 ? "LIVE" : "STALE");
  text("depthAge", ages.depth !== undefined ? `${number(ages.depth, 2)} s` : null);
  text("depthFormat", depth.encoding ? `${depth.width}×${depth.height} ${depth.encoding}` : null);

  text("collectionMode", isBatch ? "BATCH" : "SINGLE");
  text("processPid", process.pid);
  text("exitCode", process.exit_code);
  text("datasetPath", process.dataset_dir);

  const totalRounds = Number(batch.total_rounds || (isBatch ? process.config?.total_rounds : 0) || 0);
  const completedRounds = Number(batch.completed_rounds || 0);
  const percent = totalRounds > 0 ? Math.min((completedRounds / totalRounds) * 100, 100) : 0;
  $("batchProgressBar").style.width = `${percent}%`;
  const batchState = batch.state || (isBatch && process.running ? "STARTING" : "NOT STARTED");
  $("batchState").textContent = batchState;
  $("batchState").className = `state-pill ${
    batchState === "COMPLETED" ? "normal" :
    batchState === "RUNNING" || batchState === "SLEEPING" || batchState === "STARTING" ? "degraded" :
    batchState === "STOPPED" || batchState === "FAILED" ? "critical" : "unknown"
  }`;
  text("batchRounds", `${completedRounds} / ${totalRounds}`);
  text("batchSuccess", batch.success_rounds, "0");
  text("batchFailed", batch.failed_rounds, "0");
  text("batchSeed", batch.current_seed);
  text("batchLastResult", batch.last_result);

  const overall = mission.overall || "UNKNOWN";
  $("overallState").textContent = overall;
  $("overallState").className = `state-pill ${stateClass(overall)}`;
  text("localizationState", mission.localization);
  text("perceptionState", mission.perception);
  text("plannerState", mission.planner);
  text("flightState", mission.flight_safety);
  text("localizationScore", `score ${number(mission.localization_score, 3)}`);
  text("perceptionScore", `score ${number(mission.perception_score, 3)}`);
  text("plannerScore", `score ${number(mission.planner_score, 3)}`);
  text("flightScore", `score ${number(mission.flight_safety_score, 3)}`);
  text("missionSummary", mission.summary, "尚未收到 mission state。");

  text("supervisorLevel", supervisor.level);
  text("speedScale", number(supervisor.speed_scale, 2));
  text("supervisorReason", supervisor.reason);

  text("attackName", [attack.source, attack.mode, attack.severity].filter(Boolean).join(" / "));
  text("attackState", attack.active ? "ACTIVE" : attack.armed ? "ARMED" : "INACTIVE");
  text("attackElapsed", attack.elapsed_s !== undefined ? `${number(attack.elapsed_s, 1)} s` : null);
  text("attackDetail", attack.detail);
  renderRuns(data.recent_runs);

  pushTrend(mission, attack);
  drawTrends();

  if (!profilesLoaded && Array.isArray(data.profiles)) {
    const option = (profile) => `<option value="${escapeHtml(profile)}">${escapeHtml(profile)}</option>`;
    $("attackProfile").innerHTML = data.profiles.map(option).join("");
    $("liveAttackProfile").innerHTML = data.profiles.filter((p) => p !== "none").map(option).join("");
    profilesLoaded = true;
  }
}

async function refreshState() {
  try {
    renderState(await api("/api/state"));
  } catch (error) {
    setBadge($("rosBadge"), "DASHBOARD OFFLINE", "bad");
  }
}

async function refreshLog() {
  try {
    const data = await api("/api/logs?lines=220");
    $("logOutput").textContent = data.text || "尚無實驗 log。";
    $("logOutput").scrollTop = $("logOutput").scrollHeight;
  } catch (error) {
    $("logOutput").textContent = `Log 讀取失敗：${error.message}`;
  }
}

$("startButton").addEventListener("click", () => startExperiment("single"));
$("startBatchButton").addEventListener("click", () => startExperiment("batch"));
$("stopButton").addEventListener("click", stopExperiment);
$("refreshLog").addEventListener("click", refreshLog);
$("triggerAttack").addEventListener("click", triggerAttack);
$("stopAttack").addEventListener("click", stopAttack);
document.querySelectorAll("[data-level]").forEach((button) => {
  button.addEventListener("click", () => sendOverride(button.dataset.level));
});

refreshState();
refreshLog();
setInterval(refreshState, 1000);
setInterval(refreshLog, 5000);
