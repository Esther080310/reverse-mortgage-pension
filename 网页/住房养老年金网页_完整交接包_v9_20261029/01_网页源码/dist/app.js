const state = { sex: "Male", contract: "guaranteed", driftSpec: "baseline_mixture_sigma11", mainRows: [], districtRows: [], driftRows: [], crisisRows: [] };
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const number = (v) => Number.parseFloat(v);
const money = (v) => Math.round(number(v)).toLocaleString("zh-CN");
const moneyYuan = (v) => `¥${money(v)}`;
const moneyWan = (v) => `${(number(v) / 10000).toLocaleString("zh-CN", { maximumFractionDigits: 1 })} 万元`;
const percent = (v) => `${(number(v) * 100).toFixed(2)}%`;
const bool = (v) => String(v).toLowerCase() === "true";

function parseCsv(text) {
  const rows = []; let row = []; let cell = ""; let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (char === '"') {
      if (quoted && text[i + 1] === '"') { cell += '"'; i += 1; } else quoted = !quoted;
    } else if (char === "," && !quoted) { row.push(cell); cell = ""; }
    else if ((char === "\n" || char === "\r") && !quoted) {
      if (char === "\r" && text[i + 1] === "\n") i += 1;
      row.push(cell); if (row.some((v) => v.length)) rows.push(row); row = []; cell = "";
    } else cell += char;
  }
  if (cell.length || row.length) { row.push(cell); rows.push(row); }
  const headers = rows.shift();
  return rows.map((values) => Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""])));
}

async function fetchCsv(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`无法加载 ${path}`);
  return parseCsv(await response.text());
}

async function loadData() {
  const [mainRows, districtRows, driftRows, crisisRows] = await Promise.all([
    fetchCsv("./data/district_model_lookup.csv"),
    fetchCsv("./data/district_parameters.csv"),
    fetchCsv("./data/statistical_specification_sensitivity.csv"),
    fetchCsv("./data/liability_house_crisis_ratchet_path.csv"),
  ]);
  Object.assign(state, { mainRows, districtRows, driftRows, crisisRows });
}

function setSegmented(field, value) {
  state[field] = value;
  $$(`[data-field="${field}"]`).forEach((button) => button.classList.toggle("active", button.dataset.value === value));
}

function setView(view) {
  const views = { plan: "#planView", lab: "#labView", account: "#accountView" };
  const tabs = { plan: "#planTab", lab: "#labTab", account: "#accountTab" };
  Object.entries(views).forEach(([key, selector]) => { $(selector).hidden = key !== view; });
  Object.entries(tabs).forEach(([key, selector]) => {
    $(selector).classList.toggle("active", key === view);
    $(selector).setAttribute("aria-selected", String(key === view));
  });
  if (view === "lab") renderLab();
  if (view === "account") renderCrisis();
}

function selectedProfile() {
  return { segment: $("#segment").value, sex: state.sex, age: Number($("#age").value), mortality: $("#longevity").checked ? 0.15 : 0 };
}

function findMainRow() {
  const profile = selectedProfile();
  return state.mainRows.find((row) => row.segment === profile.segment && row.sex === profile.sex &&
    Number(row.start_age) === profile.age && Math.abs(number(row.mortality_improvement) - profile.mortality) < 0.001);
}

function setCoverage(covered) {
  $("#coverageBanner").hidden = true;
  $("#coverageBanner").classList.toggle("covered", covered);
  $("#coverageBanner").classList.toggle("uncovered", !covered);
  $("#coverageTitle").textContent = "暂时无法生成方案";
  $("#coverageText").textContent = "请检查填写的信息后重试。";
  $("#resultPanel").hidden = !covered;
  $("#unsupportedPanel").hidden = covered;
}

function renderPlan() {
  const row = findMainRow(); setCoverage(Boolean(row)); if (!row) return;
  const profile = selectedProfile();
  const meta = state.districtRows.find((item) => item.segment === profile.segment);
  const guaranteed = state.contract === "guaranteed";
  const prefix = guaranteed ? "guaranteed" : "adjustable";
  const monthlyPmt = number(row[`${prefix}_monthly_pmt`]);
  const actualDraw = guaranteed ? monthlyPmt : number(row.adjustable_actual_monthly_draw);
  const longLife = profile.mortality > 0 ? "更加长寿" : "一般情况";
  $("#scenarioLabel").textContent = `${row.segment_label} · ${profile.sex === "Male" ? "男性" : "女性"} · ${profile.age} 岁 · ${longLife}`;
  $("#resultTitle").textContent = guaranteed ? "保证给付方案" : "动态调额方案";
  $("#contractLabel").textContent = guaranteed ? "在世期间足额发放" : "房价恶化时可能下调";
  $("#monthlyPmt").textContent = money(monthlyPmt);
  $("#modelPropertyValue").textContent = moneyWan(row.property_value);
  $("#actualDraw").textContent = moneyYuan(actualDraw);
  $("#shortfallProbability").textContent = percent(row[`${prefix}_shortfall_probability`]);
  $("#es95").textContent = percent(row[`${prefix}_shortfall_es95_rate`]);
  $("#stopMetricLabel").textContent = guaranteed ? "停付风险" : "发生少付的可能性";
  $("#stoppedProbability").textContent = percent(guaranteed ? 0 : row.adjustable_stopped_draw_probability);
  $("#districtAverage").textContent = `${money(meta.latest_avg_price_per_sqm)} 元/㎡`;
  $("#districtVol").textContent = percent(meta.annual_house_vol);
  $("#districtTier").textContent = meta.tier;
  $("#districtDataNote").textContent = `采用 ${meta.year_start}–${meta.year_end} 年区级房价资料。`;
  if (guaranteed) {
    $("#contractNote").innerHTML = "<strong>保证给付：</strong>老人居住期间按月足额领取，房价下跌也不停发；不足部分由机构或风险资金承担。";
    $("#contractMeaning").textContent = "保证给付方案在老人居住期间按约定金额发放。房价明显下跌时产生的损失如何承担，需要在正式合同中写清楚。";
  } else {
    $("#contractNote").innerHTML = "<strong>动态调额：</strong>房价明显下跌、剩余额度不足时，每月领取金额可能下调。";
    $("#contractMeaning").textContent = "动态调额方案的起始领取金额与实际到账金额可能不同。房价明显下跌时，每月到账金额可能降低。";
  }
}

function renderDistrictComparison() {
  $("#districtResults").innerHTML = state.districtRows.map((row) => `
    <div class="district-row${row.segment === $("#segment").value ? " selected" : ""}">
      <strong>${row.district_label}</strong><span>${row.tier}</span><b>${money(row.latest_avg_price_per_sqm)} 元/㎡</b>
      <span>历史波动 ${percent(row.annual_house_vol)}</span><small>${row.missing_years ? `缺 ${row.missing_years.replaceAll("|", "、")}` : "年度完整"}</small>
    </div>`).join("");
}

function renderDrift() {
  const row = state.driftRows.find((item) => item.specification === state.driftSpec); if (!row) return;
  $("#driftPmt").textContent = moneyYuan(row.monthly_pmt);
  $("#driftProbability").textContent = percent(row.shortfall_probability);
  $("#driftEs95").textContent = percent(row.shortfall_es95_rate);
}

function renderLab() { if (state.districtRows.length) { renderDistrictComparison(); renderDrift(); } }

function renderCrisis() {
  if (!state.crisisRows.length) return;
  const month = Number($("#crisisMonth").value);
  const row = state.crisisRows.find((item) => Number(item.month) === month);
  const previous = state.crisisRows.find((item) => Number(item.month) === month - 1); if (!row) return;
  const year = number(row.year); const houseChange = previous ? number(row.house_value) / number(previous.house_value) - 1 : 0;
  const cut = bool(row.adjustable_draw_cut); const triggered = bool(row.ratchet_triggered);
  $("#crisisMonthLabel").textContent = month % 12 === 0 ? `第 ${month} 个月（${year.toFixed(0)} 年）` : `第 ${month} 个月（约 ${year.toFixed(1)} 年）`;
  $("#crisisHouse").textContent = moneyWan(row.house_value); $("#guaranteedDraw").textContent = moneyYuan(row.guaranteed_draw);
  $("#adjustableDraw").textContent = moneyYuan(row.adjustable_draw); $("#guaranteedDebt").textContent = moneyWan(row.guaranteed_debt);
  $("#adjustableDebt").textContent = moneyWan(row.adjustable_debt); $("#drawCutText").textContent = cut ? "本月发生少付" : "本月足额领取";
  $("#houseChange").textContent = month === 1 ? "起始值" : `${houseChange >= 0 ? "+" : ""}${(houseChange * 100).toFixed(1)}%`;
  $("#creditLimit").textContent = moneyWan(row.adjustable_credit_limit); $("#ratchetState").textContent = triggered ? "本月触发" : "本月未触发";
  $("#drawCutState").textContent = cut ? "动态调额发生少付" : "两类合同本月均足额"; $("#pathCheck").textContent = cut || triggered ? "需要关注" : "正常运行";
  $("#crisisStatus").lastChild.textContent = month < 120 ? "下跌前" : month === 120 ? "房价冲击发生" : "冲击后恢复期";
  $("#crisisStatus").classList.toggle("crisis", month >= 120);
}

function bindEvents() {
  $("#planTab").addEventListener("click", () => setView("plan")); $("#labTab").addEventListener("click", () => setView("lab"));
  $("#accountTab").addEventListener("click", () => setView("account"));
  $$('[data-field]').forEach((button) => button.addEventListener("click", () => {
    setSegmented(button.dataset.field, button.dataset.value); if (button.dataset.field === "driftSpec") renderDrift(); else renderPlan();
  }));
  $("#segment").addEventListener("change", () => { renderPlan(); renderDistrictComparison(); });
  $("#age").addEventListener("change", renderPlan);
  $("#longevity").addEventListener("change", renderPlan); $("#crisisMonth").addEventListener("input", renderCrisis);
}

async function start() {
  $("#age").innerHTML = Array.from({ length: 31 }, (_, index) => {
    const age = 60 + index;
    return `<option value="${age}"${age === 70 ? " selected" : ""}>${age} 岁</option>`;
  }).join("");
  bindEvents();
  try { await loadData(); renderPlan(); renderLab(); renderCrisis(); }
  catch (error) { setCoverage(false); $("#coverageText").textContent = `数据加载失败：${error.message}`; }
}
start();
