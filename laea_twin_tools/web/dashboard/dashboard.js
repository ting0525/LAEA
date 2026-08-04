const $ = (id) => document.getElementById(id);
let profilesLoaded = false;
let worldsLoaded = false;
let lastProcessPid = null;

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

function capabilityLabel(value) {
  return String(value || "unknown").replaceAll("_", " ").toUpperCase();
}

function formatAttackMagnitude(command) {
  const source = String(command.source || "");
  const vector = Array.isArray(command.vector) ? command.vector : [];
  if (source === "barometer") {
    return `${number(command.scalar, 2)} m altitude offset`;
  }
  if (source === "imu") {
    if (vector.length < 3) return "—";
    return `[${vector.map((value) => number(value, 2)).join(", ")}] rad/s`;
  }
  if (vector.length < 3) return "—";
  const unit = command.mode === "velocity_bias" ? "m/s" : "m";
  return `[${vector.map((value) => number(value, 2)).join(", ")}] ${unit}`;
}

function profileMagnitudeLabel(profile) {
  if (profile.source === "barometer") {
    const scalar = Math.abs(Number(profile.scalar) || 0);
    return scalar > 0 ? `${number(scalar, 1)} m` : "";
  }
  if (profile.source === "imu") {
    const vector = Array.isArray(profile.vector) ? profile.vector : [];
    const yawRate = Math.abs(Number(vector[2]) || 0);
    return yawRate > 0 ? `${number(yawRate, 2)} rad/s` : "";
  }
  const vector = Array.isArray(profile.vector) ? profile.vector : [];
  const primary = Math.abs(Number(vector[0]) || 0);
  if (primary > 0) {
    const unit = profile.mode === "velocity_bias" ? "m/s" : "m";
    return `${number(primary, 1)} ${unit}`;
  }
  const scalar = Math.abs(Number(profile.scalar) || 0);
  return scalar > 0 ? number(scalar, 1) : "";
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
    manual_attack: $("manualAttack").checked,
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
  if (!confirm("停止目前實驗並清理所有相關程序？")) return;
  try {
    $("actionMessage").textContent = "正在停止實驗並清理所有元件…";
    const result = await api("/api/experiment/stop", { method: "POST", body: "{}" });
    const report = result.process?.stop_report || {};
    $("actionMessage").textContent = report.cleanup_complete
      ? "實驗已停止並清理完成。"
      : `停止未完全：PID ${(report.remaining_pids || []).join(", ") || "無"}；ROS node ${(report.remaining_ros_nodes || []).join(", ") || "無"}。`;
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
const SENSOR_MAX = 240;
const sensorTrend = [];

const SENSOR_CHARTS = {
  gps: {
    canvas: "gpsSensorCanvas",
    now: "gpsSensorNow",
    peak: "gpsSensorPeak",
    ref: "gpsSensorRef",
    unit: "m",
    supportUnit: "m",
    primaryLabel: "gps_pos_res",
    supportLabel: "localization drift",
    degraded: 2.0,
    critical: 5.0,
  },
  imu: {
    canvas: "imuSensorCanvas",
    now: "imuSensorNow",
    peak: "imuSensorPeak",
    ref: "imuSensorRef",
    unit: "rad/s",
    supportUnit: "rad/s",
    primaryLabel: "yaw_rate_res",
    supportLabel: "commanded gyro z",
    degraded: 0.25,
    critical: 0.70,
  },
  barometer: {
    canvas: "baroSensorCanvas",
    now: "baroSensorNow",
    peak: "baroSensorPeak",
    ref: "baroSensorRef",
    unit: "m",
    supportUnit: "m",
    primaryLabel: "baro_res",
    supportLabel: "altitude drift",
    degraded: 0.8,
    critical: 2.0,
  },
};

function finite(value) {
  return Number.isFinite(Number(value));
}

function pushTrend(mission, attackActive) {
  trend.push({
    loc: Number(mission.localization_score) || 0,
    perc: Number(mission.perception_score) || 0,
    plan: Number(mission.planner_score) || 0,
    flight: Number(mission.flight_safety_score) || 0,
    attack: Boolean(attackActive),
  });
  while (trend.length > TREND_MAX) trend.shift();
}

function pushSensorTrend(metrics, activeCmd, attackActive) {
  const gps = metrics.gps || {};
  const imu = metrics.imu || {};
  const barometer = metrics.barometer || {};
  const vector = Array.isArray(activeCmd.vector) ? activeCmd.vector : [];
  const commandSource = activeCmd.enabled ? activeCmd.source : "none";

  sensorTrend.push({
    attack: Boolean(attackActive),
    gps: {
      primary: finite(gps.gps_pos_res) ? Number(gps.gps_pos_res) : null,
      support: finite(gps.localization_drift_m) ? Number(gps.localization_drift_m) : null,
      aux: finite(gps.gps_vel_res) ? Number(gps.gps_vel_res) : null,
    },
    imu: {
      primary: finite(imu.yaw_rate_res) ? Number(imu.yaw_rate_res) : null,
      support: commandSource === "imu" && finite(vector[2]) ? Math.abs(Number(vector[2])) : null,
    },
    barometer: {
      primary: finite(barometer.baro_res) ? Number(barometer.baro_res) : null,
      support: finite(barometer.altitude_drift_m) ? Number(barometer.altitude_drift_m) : null,
      aux: commandSource === "barometer" && finite(activeCmd.scalar) ? Number(activeCmd.scalar) : null,
    },
  });
  while (sensorTrend.length > SENSOR_MAX) sensorTrend.shift();
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

  const pad = { l: 8, r: 8, t: 8, b: 8 };
  const plotW = w - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;
  const yMax = 3;
  const visibleIntervals = Math.max(trend.length - 1, 1);
  const xAt = (i) => pad.l + (i / visibleIntervals) * plotW;
  const yAt = (v) => pad.t + plotH - Math.min(Math.max(v, 0), yMax) / yMax * plotH;

  if (trend.length === 0) {
    ctx.fillStyle = "#8faca4";
    ctx.font = "13px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("等待 Mission State 資料", w / 2, h / 2);
    ctx.textAlign = "start";
    return;
  }

  ctx.fillStyle = "rgba(255, 107, 107, .16)";
  for (let i = 0; i < trend.length; i++) {
    if (trend[i].attack) {
      const x0 = xAt(i);
      const x1 = xAt(Math.min(i + 1, TREND_MAX - 1));
      ctx.fillRect(x0, pad.t, Math.max(x1 - x0, 1.5), plotH);
    }
  }

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

    const latestIndex = trend.length - 1;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(xAt(latestIndex), yAt(trend[latestIndex][key]), 3, 0, Math.PI * 2);
    ctx.fill();
  }
}

function drawLine(ctx, samples, valueFor, xAt, yAt, color, dashed = false) {
  ctx.strokeStyle = color;
  ctx.lineWidth = dashed ? 1.3 : 2.0;
  ctx.setLineDash(dashed ? [5, 5] : []);
  ctx.beginPath();
  let hasPoint = false;
  for (let i = 0; i < samples.length; i++) {
    const value = valueFor(samples[i]);
    if (!finite(value)) continue;
    const x = xAt(i);
    const y = yAt(Number(value));
    if (!hasPoint) {
      ctx.moveTo(x, y);
      hasPoint = true;
    } else {
      ctx.lineTo(x, y);
    }
  }
  if (hasPoint) ctx.stroke();
  ctx.setLineDash([]);
}

function drawThreshold(ctx, value, label, color, x, width, yAt) {
  if (!finite(value)) return;
  const y = yAt(Number(value));
  ctx.strokeStyle = color;
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(x + width, y);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = color;
  ctx.font = "10px sans-serif";
  ctx.fillText(label, x + width - 58, y - 4);
}

function drawSensorChart(key, config) {
  const canvas = $(config.canvas);
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 360;
  const h = canvas.clientHeight || 190;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const samples = sensorTrend;
  const latest = [...samples].reverse().find((sample) => finite(sample[key]?.primary));
  const values = samples.flatMap((sample) => [sample[key]?.primary, sample[key]?.support])
    .filter((value) => finite(value))
    .map(Number);
  const peak = values.length ? Math.max(...values) : null;
  text(config.now, latest ? `${number(latest[key].primary, config.unit === "rad/s" ? 3 : 2)} ${config.unit}` : null);
  text(config.peak, peak !== null ? `peak ${number(peak, config.unit === "rad/s" ? 3 : 2)} ${config.unit}` : "peak —");

  const supportLatest = [...samples].reverse().find((sample) => finite(sample[key]?.support));
  const auxLatest = [...samples].reverse().find((sample) => finite(sample[key]?.aux));
  const supportText = supportLatest
    ? `${config.supportLabel} ${number(supportLatest[key].support, config.supportUnit === "rad/s" ? 3 : 2)} ${config.supportUnit}`
    : auxLatest
      ? `command ${number(auxLatest[key].aux, 2)} ${config.unit}`
      : "reference —";
  text(config.ref, supportText);

  const pad = { l: 38, r: 10, t: 12, b: 22 };
  const plotW = w - pad.l - pad.r;
  const plotH = h - pad.t - pad.b;
  const yMax = Math.max(config.critical * 1.2, peak !== null ? peak * 1.15 : 0, config.degraded * 1.6, 1.0e-6);
  const visibleIntervals = Math.max(samples.length - 1, 1);
  const xAt = (i) => pad.l + (i / visibleIntervals) * plotW;
  const yAt = (v) => pad.t + plotH - Math.min(Math.max(v, 0), yMax) / yMax * plotH;

  ctx.fillStyle = "rgba(255, 107, 107, .13)";
  for (let i = 0; i < samples.length; i++) {
    if (samples[i].attack) {
      const x0 = xAt(i);
      const x1 = xAt(Math.min(i + 1, SENSOR_MAX - 1));
      ctx.fillRect(x0, pad.t, Math.max(x1 - x0, 1.5), plotH);
    }
  }

  ctx.strokeStyle = "rgba(143, 172, 164, .22)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 3; i++) {
    const y = pad.t + (plotH / 3) * i;
    ctx.beginPath();
    ctx.moveTo(pad.l, y);
    ctx.lineTo(pad.l + plotW, y);
    ctx.stroke();
  }
  ctx.fillStyle = "#8faca4";
  ctx.font = "10px sans-serif";
  ctx.textAlign = "right";
  ctx.fillText(number(yMax, config.unit === "rad/s" ? 2 : 1), pad.l - 5, pad.t + 4);
  ctx.fillText("0", pad.l - 5, pad.t + plotH);
  ctx.textAlign = "start";

  if (samples.length === 0 || values.length === 0) {
    ctx.fillStyle = "#8faca4";
    ctx.font = "13px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("等待感測器資料", w / 2, h / 2);
    ctx.textAlign = "start";
    return;
  }

  drawThreshold(ctx, config.degraded, "DEG", "#f2c14e", pad.l, plotW, yAt);
  drawThreshold(ctx, config.critical, "CRIT", "#ff6b6b", pad.l, plotW, yAt);
  drawLine(ctx, samples, (sample) => sample[key]?.support, xAt, yAt, "#49d49d", true);
  drawLine(ctx, samples, (sample) => sample[key]?.primary, xAt, yAt, "#55c2d9", false);

  if (latest) {
    const latestIndex = samples.lastIndexOf(latest);
    ctx.fillStyle = "#55c2d9";
    ctx.beginPath();
    ctx.arc(xAt(latestIndex), yAt(latest[key].primary), 3.5, 0, Math.PI * 2);
    ctx.fill();
  }
}

function drawSensorCharts() {
  for (const [key, config] of Object.entries(SENSOR_CHARTS)) {
    drawSensorChart(key, config);
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

function renderWorldCatalog(catalog) {
  if (worldsLoaded || !Array.isArray(catalog)) return;
  const selectedName = $("worldName").value || "indoor_01";
  $("worldName").innerHTML = catalog.map((item) => {
    const disabled = item.available ? "" : " disabled";
    const suffix = item.available ? "" : "（檔案不可用）";
    return `<option value="${escapeHtml(item.name)}"${disabled}>${escapeHtml(item.label || item.name)}${suffix}</option>`;
  }).join("");
  if (catalog.some((item) => item.name === selectedName && item.available)) {
    $("worldName").value = selectedName;
  }
  worldsLoaded = true;
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
  const components = data.components || {};
  const telemetryFresh = Boolean(
    process.running
    && ages.mavros !== undefined
    && ages.mavros < 2
  );

  setBadge($("rosBadge"), data.ros_master_online ? "ROS ONLINE" : "ROS OFFLINE", data.ros_master_online ? "good" : "bad");
  setBadge(
    $("dataBadge"),
    telemetryFresh ? "DATA LIVE" : process.running ? "DATA STALE" : "DATA STOPPED",
    telemetryFresh ? "good" : process.running ? "bad" : "neutral",
  );
  const processLabel = process.running
    ? isBatch
      ? "COLLECTING DATA"
      : "EXPERIMENT RUNNING"
    : process.cleanup_needed
      ? "CLEANUP REQUIRED"
      : "IDLE";
  setBadge(
    $("processBadge"),
    processLabel,
    process.running || process.cleanup_needed ? "warning" : "neutral",
  );
  $("startButton").disabled = Boolean(process.running || process.cleanup_needed);
  $("startBatchButton").disabled = Boolean(process.running || process.cleanup_needed);
  $("stopButton").disabled = !(process.running || process.cleanup_needed);
  const attackReady = Boolean(
    process.running
    && process.config?.attack_capable_model
    && components.gazebo?.online
    && components.attack_bridge?.online
  );
  $("triggerAttack").disabled = !attackReady;
  $("stopAttack").disabled = !process.running;
  document.querySelectorAll("[data-level]").forEach((button) => {
    button.disabled = !process.running;
  });

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
  const runtimeProfile = process.config?.runtime_profile || "scan_mapping_explore_test";
  text("currentProfile", runtimeProfile);
  text("processPid", process.pid);
  text("exitCode", process.exit_code);
  text("datasetPath", process.dataset_dir);

  const totalRounds = Number(batch.total_rounds || (isBatch ? process.config?.total_rounds : 0) || 0);
  const completedRounds = Number(batch.completed_rounds || 0);
  const hasBatchProgress = Boolean(
    batch.state || batch.total_rounds || batch.completed_rounds || batch.success_rounds || batch.failed_rounds
  );
  $("batchPanel").hidden = !(isBatch || hasBatchProgress);
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

  const activeCmd = telemetry.active_command || {};
  const evidence = telemetry.attack_evidence || {};
  const gt = telemetry.ground_truth || {};
  const drift = telemetry.localization_drift_m;
  const cmdEnabled = Boolean(activeCmd.enabled && activeCmd.source !== "none");
  const attackEffectActive = Boolean(attack.active || activeCmd.effect_active);
  const attackIdentity = cmdEnabled ? activeCmd : attack;
  text("attackName", [attackIdentity.source, attackIdentity.mode, attackIdentity.severity].filter(Boolean).join(" / "));
  text(
    "attackState",
    activeCmd.effect_active
      ? capabilityLabel(activeCmd.phase)
      : attack.active
        ? "ACTIVE"
        : attack.armed
          ? "ARMED"
          : "INACTIVE",
  );
  text(
    "attackElapsed",
    cmdEnabled
      ? `${number(activeCmd.elapsed_s, 1)} s`
      : attack.elapsed_s !== undefined
        ? `${number(attack.elapsed_s, 1)} s`
        : null,
  );
  text("attackDetail", cmdEnabled ? `command ${activeCmd.phase || "published"}` : attack.detail);

  $("attackEffectPill").textContent = cmdEnabled ? `COMMAND ${capabilityLabel(activeCmd.phase)}` : "NO ATTACK";
  $("attackEffectPill").className = `state-pill ${attackEffectActive ? "critical" : cmdEnabled ? "degraded" : "normal"}`;
  const evidenceIdentity = evidence.command_start_s > 0 ? evidence : activeCmd;
  const evidenceUnit = evidence.metric_unit || telemetry.attack_metric_unit || "m";
  const metricDigits = evidenceUnit === "rad/s" ? 3 : 2;
  const metricText = (value, prefix = "") => (
    Number.isFinite(Number(value)) ? `${prefix}${number(value, metricDigits)} ${evidenceUnit}` : null
  );
  const pathOnline = Boolean(components.gazebo?.online && components.attack_bridge?.online);
  text("evidenceRun", process.pid ? `${isBatch ? "BATCH" : "SINGLE"} / PID ${process.pid}` : null);
  text("evidenceWorld", process.config?.world_name);
  text("evidencePath", pathOnline ? "ROS → Gazebo bridge ONLINE" : "OFFLINE");
  text("evidenceCapturedAt", new Date().toLocaleString());
  text("diagCmd", [evidenceIdentity.source, evidenceIdentity.mode, evidenceIdentity.severity].filter((value) => value && value !== "none").join(" / "));
  text("evidenceMagnitude", formatAttackMagnitude(evidenceIdentity));
  text("evidencePhase", `${capabilityLabel(evidence.phase || activeCmd.phase)} / ${number(activeCmd.elapsed_s, 1)} s`);
  text("evidenceMetricLabel", evidence.metric_label || telemetry.attack_metric_label || "Localization drift");
  text("evidenceBaseline", metricText(evidence.baseline_drift_m));
  text("driftValue", metricText(evidence.current_drift_m ?? telemetry.attack_metric_value ?? drift));
  text("evidencePeak", metricText(evidence.peak_drift_m));
  text("evidenceIncrease", metricText(evidence.drift_increase_m, "+"));
  text("gtValue", Number.isFinite(gt.x) ? `${number(gt.x)} / ${number(gt.y)} / ${number(gt.z)} m` : null);
  text("ekfValue", Number.isFinite(pose.x) ? `${number(pose.x)} / ${number(pose.y)} / ${number(pose.z)} m` : null);
  text("evidenceLocalization", `${mission.localization || "UNKNOWN"} / score ${number(mission.localization_score, 3)}`);
  text("evidenceOverall", mission.overall);
  const evidenceResult = !process.running
    ? "WAITING FOR RUN"
    : !pathOnline
      ? "INJECTION PATH OFFLINE"
      : evidence.impact_observed
        ? "IMPACT OBSERVED"
        : cmdEnabled
          ? "MEASURING"
          : "READY";
  text("evidenceResult", evidenceResult);
  text("evidenceSummary", mission.summary, "等待攻擊實驗資料。");

  renderRuns(data.recent_runs);
  renderWorldCatalog(data.world_catalog);

  if (process.pid && process.pid !== lastProcessPid) {
    trend.length = 0;
    sensorTrend.length = 0;
    lastProcessPid = process.pid;
  }
  if (telemetryFresh && ages.mission !== undefined && ages.mission < 2) {
    pushTrend(mission, attackEffectActive);
    pushSensorTrend(telemetry.sensor_metrics || {}, activeCmd, attackEffectActive);
  }
  drawTrends();
  drawSensorCharts();

  if (!profilesLoaded && Array.isArray(data.profile_catalog)) {
    const option = (item) => {
      const disabled = item.live_supported ? "" : " disabled";
      const magnitude = profileMagnitudeLabel(item);
      const suffix = item.live_supported
        ? magnitude ? ` — ${magnitude}` : ""
        : "（injector 尚未接通）";
      return `<option value="${escapeHtml(item.name)}"${disabled}>${escapeHtml(item.name)}${suffix}</option>`;
    };
    $("attackProfile").innerHTML = data.profile_catalog.map(option).join("");
    $("liveAttackProfile").innerHTML = data.profile_catalog
      .filter((item) => item.name !== "none")
      .map(option)
      .join("");
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
$("evidenceModeButton").addEventListener("click", () => {
  const enabled = document.body.classList.toggle("evidence-mode");
  $("evidenceModeButton").textContent = enabled ? "離開數據模式" : "數據模式";
  if (enabled) {
    $("attackEvidencePanel").scrollIntoView({ behavior: "smooth", block: "start" });
  }
});
if (new URLSearchParams(window.location.search).get("evidence") === "1") {
  document.body.classList.add("evidence-mode");
  $("evidenceModeButton").textContent = "離開數據模式";
}
$("triggerAttack").addEventListener("click", triggerAttack);
$("stopAttack").addEventListener("click", stopAttack);
document.querySelectorAll("[data-level]").forEach((button) => {
  button.addEventListener("click", () => sendOverride(button.dataset.level));
});

refreshState();
refreshLog();
setInterval(refreshState, 1000);
setInterval(refreshLog, 5000);
