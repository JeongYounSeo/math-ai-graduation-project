"use strict";

/* ---------------------------------------------------------------
 * Math Problem Engine · Admin console
 * Static, dependency-free SPA that talks to the existing FastAPI
 * JSON endpoints. No build step required.
 * ------------------------------------------------------------- */

const STATUS_LABEL = {
  unclassified: "미분류",
  classified: "분류 완료",
  excluded: "제외됨",
};

const state = {
  currentView: "dashboard",
  sourcePdfs: [],
  solutionModules: [],
  typeCombinations: [],
  problemsCache: [],
  cropReview: null,
  cropPreparing: new Set(),
  cropPreparingAll: false,
  cropEditor: null,
};

/* ---------------- fetch helpers ---------------- */

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: options.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail ? JSON.stringify(data.detail) : JSON.stringify(data);
    } catch (_) {
      /* ignore parse errors */
    }
    throw new Error(`${res.status} ${detail}`);
  }
  if (res.status === 204) return null;
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

function toast(message, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.toggle("err", isError);
  el.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove("show"), 3200);
}

/* ---------------- view switching ---------------- */

const VIEW_TITLES = {
  dashboard: "대시보드",
  "pdf-import": "PDF 업로드",
  problems: "문제함",
  "solution-modules": "소유형 모듈",
  "concept-modules": "개념 모듈",
  "type-combinations": "유형 조합",
  analyze: "문제 분석 테스트 (Mock)",
  generate: "문제 생성 (Mock)",
};

function switchView(view) {
  if (!VIEW_TITLES[view]) view = "dashboard";
  state.currentView = view;

  document.querySelectorAll(".view").forEach((el) => el.classList.add("hidden"));
  document.getElementById(`view-${view}`).classList.remove("hidden");

  document.querySelectorAll(".nav-item").forEach((el) => {
    el.classList.toggle("active", el.dataset.view === view);
  });

  document.getElementById("view-title").textContent = VIEW_TITLES[view];
  location.hash = view;

  const loaders = {
    dashboard: loadDashboard,
    "pdf-import": loadPdfImportView,
    problems: loadProblemsView,
    "solution-modules": loadSolutionModulesView,
    "concept-modules": loadConceptModulesView,
    "type-combinations": loadTypeCombinationsView,
    generate: loadGenerateView,
  };
  if (loaders[view]) loaders[view]();
}

/* ---------------- dashboard ---------------- */

async function loadDashboard() {
  const grid = document.getElementById("stat-grid");
  grid.innerHTML = `<div class="stat-card"><div class="stat-num">…</div><div class="stat-label">불러오는 중</div></div>`;

  try {
    const [unclassified, classified, excluded, sourcePdfs, modules, concepts, combos] = await Promise.all([
      api("/api/problems/?status=unclassified&page_size=1000"),
      api("/api/problems/?status=classified&page_size=1000"),
      api("/api/problems/?status=excluded&page_size=1000"),
      api("/api/pdf-import/source-pdfs"),
      api("/solution-modules/"),
      api("/concept-modules/"),
      api("/type-combinations/"),
    ]);

    const stats = [
      { label: "미분류 문제", num: unclassified.length, tone: "mock" },
      { label: "분류 완료 문제", num: classified.length, tone: "live" },
      { label: "제외된 문제", num: excluded.length, tone: "" },
      { label: "업로드된 PDF", num: sourcePdfs.length, tone: "" },
      { label: "소유형 모듈", num: modules.length, tone: "" },
      { label: "개념 모듈", num: concepts.length, tone: "" },
      { label: "유형 조합", num: combos.length, tone: "" },
    ];

    grid.innerHTML = stats
      .map(
        (s) => `<div class="stat-card"><div class="stat-num">${s.num}</div><div class="stat-label">${s.label}</div></div>`
      )
      .join("");
  } catch (e) {
    grid.innerHTML = `<div class="stat-card"><div class="stat-num">–</div><div class="stat-label">통계를 불러오지 못했습니다</div></div>`;
    toast(`대시보드 로딩 실패: ${e.message}`, true);
  }
}

/* ---------------- PDF import ---------------- */

function statusPill(status) {
  return `<span class="status-pill ${status || ""}">${STATUS_LABEL[status] || status || "-"}</span>`;
}

async function loadPdfImportView() {
  const tbody = document.getElementById("source-pdf-tbody");
  tbody.innerHTML = `<tr><td colspan="6" class="empty">불러오는 중…</td></tr>`;
  try {
    const list = await api("/api/pdf-import/source-pdfs");
    state.sourcePdfs = list;
    if (!list.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty">아직 업로드된 PDF가 없습니다</td></tr>`;
      return;
    }
    tbody.innerHTML = list
      .map(
        (p) => `
      <tr>
        <td>${p.source_pdf_id}</td>
        <td>${escapeHtml(p.original_filename)}</td>
        <td>${p.total_pages}</td>
        <td>${statusPill(p.status)}</td>
        <td>${formatDate(p.created_at)}</td>
        <td>${p.status === "awaiting_review" ? `<button class="btn btn-primary" data-review-pdf="${p.source_pdf_id}">Crop 검토</button>` : `<button class="btn" data-goto-pdf="${p.source_pdf_id}">문제 보기</button>`}</td>
      </tr>`
      )
      .join("");

    tbody.querySelectorAll("[data-goto-pdf]").forEach((btn) => {
      btn.addEventListener("click", () => {
        switchView("problems");
        setTimeout(() => {
          document.getElementById("filter-status").value = "";
          document.getElementById("filter-source-pdf").value = btn.dataset.gotoPdf;
          applyProblemFilter();
        }, 0);
      });
    });
    tbody.querySelectorAll("[data-review-pdf]").forEach((btn) => {
      btn.addEventListener("click", () => openCropReview(btn.dataset.reviewPdf));
    });
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty">불러오기 실패: ${escapeHtml(e.message)}</td></tr>`;
  }
}

function setupUploadForm() {
  document.getElementById("upload-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const fileInput = document.getElementById("pdf-file");
    const resultEl = document.getElementById("upload-result");
    if (!fileInput.files.length) return;

    const fd = new FormData();
    fd.append("file", fileInput.files[0]);
    resultEl.textContent = "업로드 및 페이지 렌더링 중…";

    try {
      const result = await api("/api/pdf-import/review-uploads", { method: "POST", body: fd });
      resultEl.textContent = `업로드 완료: ${result.total_pages}페이지 (source_pdf_id: ${result.source_pdf_id})`;
      toast("PDF 업로드 완료. Crop을 검토해 주세요.");
      fileInput.value = "";
      loadPdfImportView();
      await openCropReview(result.source_pdf_id);
    } catch (e) {
      resultEl.textContent = `실패: ${e.message}`;
      toast("PDF 업로드 실패", true);
    }
  });
}

/* ---------------- Staged outer-crop review ---------------- */

async function openCropReview(sourceId) {
  try {
    if (state.cropEditor) closeCropEditor();
    state.cropReview = await api(`/api/pdf-import/source-pdfs/${sourceId}/crop-review`);
    renderCropReview();
    const nextPage = state.cropReview.pages.find((page) => !page.confirmed) || state.cropReview.pages[0];
    openCropEditor(nextPage.page_number, null);
    if (state.cropReview.status !== "reviewed") prepareAllCropPages();
  } catch (e) {
    toast(`검토 화면 로딩 실패: ${e.message}`, true);
  }
}

function renderCropReview() {
  const review = state.cropReview;
  if (!review) return;
  {
    document.getElementById("crop-review-panel").classList.remove("hidden");
    document.getElementById("crop-review-title").textContent = `${review.original_filename} · Crop 검토`;
    const preparedCount = review.pages.filter((page) => page.status !== "unprepared").length;
    const confirmedCount = review.pages.filter((page) => page.confirmed).length;
    document.getElementById("crop-review-progress").textContent = `${preparedCount}/${review.total_pages}페이지 제안 · ${confirmedCount}/${review.total_pages}페이지 채택`;
    document.getElementById("crop-review-pages").textContent = "검토 화면에서 박스를 조절하고 필요 없는 영역을 버린 뒤 페이지를 채택하세요.";
    const picker = document.getElementById("crop-workspace-page");
    picker.innerHTML = review.pages.map((page) => `<option value="${page.page_number}">${page.page_number}페이지 · ${page.confirmed ? "채택" : page.status === "unprepared" ? "준비 중" : "검토 중"}</option>`).join("");
    if (state.cropEditor) {
      const page = review.pages[state.cropEditor.pageNumber - 1];
      picker.value = String(page.page_number);
      if (state.cropEditor.box == null && !state.cropEditor.userDraft && !state.cropEditor.noAutoSelect && page.proposals.length) {
        const proposal = page.proposals.find((item) => item.decision === "pending") || page.proposals[0];
        state.cropEditor.proposalId = proposal.id;
        state.cropEditor.box = { ...proposal.crop_box };
      }
      const pending = page.proposals.filter((item) => item.decision === "pending").length;
      document.getElementById("crop-workspace-status").textContent = `${page.page_number}/${review.total_pages}페이지 · 후보 ${page.proposals.length}개 · 미판정 ${pending}개${page.confirmed ? " · 채택 완료" : ""}`;
      document.getElementById("crop-workspace-reason").textContent = page.reason || "";
      renderCropEditorBox();
    }
    const finalize = document.getElementById("crop-finalize");
    finalize.disabled = confirmedCount !== review.total_pages || review.status === "reviewed";
    finalize.textContent = review.status === "reviewed" ? "문제함 등록 완료" : "검토 완료 · 문제함에 등록";
  }

}

async function prepareCropPage(pageNumber) {
  if (state.cropPreparing.has(pageNumber)) return;
  state.cropPreparing.add(pageNumber);
  const button = document.querySelector(`[data-crop-prepare="${pageNumber}"]`);
  if (button) { button.disabled = true; button.textContent = "후보 생성 중…"; }
  const review = state.cropReview;
  const page = review.pages[pageNumber - 1];
  const action = page.status === "unprepared" ? "prepare" : "retry";
  try {
    toast(`${pageNumber}페이지 후보를 생성 중입니다…`);
    state.cropReview = await api(`/api/pdf-import/source-pdfs/${review.source_pdf_id}/crop-review/pages/${pageNumber}/${action}`, { method: "POST" });
    renderCropReview();
  } catch (e) { toast(`후보 생성 실패: ${e.message}`, true); }
  finally {
    state.cropPreparing.delete(pageNumber);
    if (button && button.isConnected) {
      button.disabled = false;
      button.textContent = action === "prepare" ? "후보 생성" : "이 페이지 다시 제안받기";
    }
  }
}

async function prepareAllCropPages() {
  if (state.cropPreparingAll || !state.cropReview) return;
  state.cropPreparingAll = true;
  renderCropReview();
  const sourceId = state.cropReview.source_pdf_id;
  for (const page of state.cropReview.pages) {
    if (!state.cropReview || state.cropReview.source_pdf_id !== sourceId) break;
    if (page.status === "unprepared") await prepareCropPage(page.page_number);
  }
  state.cropPreparingAll = false;
  renderCropReview();
}

function openCropEditor(pageNumber, proposalId) {
  if (!state.cropReview || state.cropReview.status === "reviewed") return;
  const page = state.cropReview.pages[pageNumber - 1];
  const proposal = proposalId === 0 ? null : proposalId == null
    ? page.proposals.find((p) => p.decision === "pending") || page.proposals[0] || null
    : page.proposals.find((p) => p.id === proposalId);
  if (proposalId != null && proposalId !== 0 && !proposal) { toast("현재 후보를 찾을 수 없습니다.", true); return; }
  state.cropEditor = {
    pageNumber, proposalId: proposal?.id || null,
    box: proposal ? { ...proposal.crop_box } : null,
    width: page.image_width, height: page.image_height,
    drag: null, userDraft: false, noAutoSelect: proposalId === 0,
  };
  document.getElementById("crop-editor-title").textContent = `${state.cropReview.original_filename} · Crop 검토`;
  document.getElementById("crop-editor-modal").classList.remove("hidden");
  const image = document.getElementById("crop-editor-image");
  image.onload = () => {
    if (!state.cropEditor || state.cropEditor.pageNumber !== pageNumber) return;
    renderCropEditorBox();
    const scroll = document.getElementById("crop-editor-scroll");
    scroll.scrollTop = state.cropEditor.box ? Math.max(0, state.cropEditor.box.y / page.image_height * image.clientHeight - 80) : 0;
  };
  image.src = page.page_image_url;
  renderCropReview();
}

function closeCropEditor() {
  document.getElementById("crop-editor-modal").classList.add("hidden");
  state.cropEditor = null;
}

function renderCropEditorBox() {
  const editor = state.cropEditor;
  const boxEl = document.getElementById("crop-editor-box");
  if (!editor) return;
  const page = state.cropReview.pages[editor.pageNumber - 1];
  const others = document.getElementById("crop-editor-other-boxes");
  others.innerHTML = page.proposals.filter((p) => p.id !== editor.proposalId).map((p, index) => {
    const b = p.crop_box;
    return `<button type="button" class="crop-editor-other-box ${p.decision}" data-select-proposal="${p.id}" style="left:${b.x / editor.width * 100}%;top:${b.y / editor.height * 100}%;width:${b.width / editor.width * 100}%;height:${b.height / editor.height * 100}%">${p.problem_number || index + 1}</button>`;
  }).join("");
  others.querySelectorAll("[data-select-proposal]").forEach((button) => {
    button.addEventListener("pointerdown", (event) => event.stopPropagation());
    button.addEventListener("click", () => {
      const selected = page.proposals.find((p) => p.id === Number(button.dataset.selectProposal));
      editor.proposalId = selected.id;
      editor.box = { ...selected.crop_box };
      editor.userDraft = false;
      renderCropEditorBox();
    });
  });
  const accept = document.getElementById("crop-editor-accept");
  const discard = document.getElementById("crop-editor-discard");
  const readOnly = state.cropReview.status === "reviewed";
  accept.disabled = readOnly || page.status === "unprepared" || Boolean(editor.box && (editor.box.width < 20 || editor.box.height < 20));
  discard.disabled = readOnly || !editor.box;
  if (!editor.box) {
    boxEl.classList.add("hidden");
    document.getElementById("crop-editor-coordinates").textContent = "필요하면 빈 곳을 드래그해 새 문제 영역을 그리세요.";
    document.getElementById("crop-workspace-preview").textContent = "선택한 후보 없음";
    return;
  }
  const b = editor.box;
  boxEl.classList.remove("hidden");
  boxEl.style.left = `${b.x / editor.width * 100}%`;
  boxEl.style.top = `${b.y / editor.height * 100}%`;
  boxEl.style.width = `${b.width / editor.width * 100}%`;
  boxEl.style.height = `${b.height / editor.height * 100}%`;
  document.getElementById("crop-editor-coordinates").textContent = `선택 영역: x ${b.x}, y ${b.y} · ${b.width} × ${b.height}px`;
  if (!editor.drag) updateCropWorkspacePreview();
}

function updateCropWorkspacePreview() {
  const editor = state.cropEditor;
  const image = document.getElementById("crop-editor-image");
  if (!editor?.box || !image.naturalWidth || editor.box.width < 20 || editor.box.height < 20) return;
  const preview = document.getElementById("crop-workspace-preview");
  const canvas = document.createElement("canvas");
  canvas.width = editor.box.width;
  canvas.height = editor.box.height;
  canvas.getContext("2d").drawImage(image, editor.box.x, editor.box.y,
    editor.box.width, editor.box.height, 0, 0, canvas.width, canvas.height);
  preview.replaceChildren(canvas);
}

function cropEditorPoint(event) {
  const editor = state.cropEditor;
  const rect = document.getElementById("crop-editor-image").getBoundingClientRect();
  return {
    x: Math.round(Math.max(0, Math.min(editor.width, (event.clientX - rect.left) / rect.width * editor.width))),
    y: Math.round(Math.max(0, Math.min(editor.height, (event.clientY - rect.top) / rect.height * editor.height))),
  };
}

function setupCropEditor() {
  const canvas = document.getElementById("crop-editor-canvas");
  canvas.addEventListener("pointerdown", (event) => {
    const editor = state.cropEditor;
    if (!editor || event.button !== 0 || !document.getElementById("crop-editor-image").naturalWidth) return;
    const handle = event.target.closest("[data-handle]");
    const onBox = event.target.closest("#crop-editor-box");
    const mode = handle ? handle.dataset.handle : onBox && editor.box ? "move" : "draw";
    const point = cropEditorPoint(event);
    editor.drag = { mode, pointerId: event.pointerId, start: point,
                    initial: editor.box ? { ...editor.box } : null };
    if (mode === "draw") {
      editor.proposalId = null;
      editor.userDraft = true;
      editor.box = { x: point.x, y: point.y, width: 0, height: 0 };
    }
    event.preventDefault();
    renderCropEditorBox();
  });
  window.addEventListener("pointermove", (event) => {
    const editor = state.cropEditor;
    if (!editor?.drag || editor.drag.pointerId !== event.pointerId) return;
    const { mode, start, initial } = editor.drag;
    const point = cropEditorPoint(event);
    if (mode === "draw") {
      editor.box = { x: Math.min(start.x, point.x), y: Math.min(start.y, point.y),
                     width: Math.abs(point.x - start.x), height: Math.abs(point.y - start.y) };
    } else if (mode === "move") {
      editor.box = { ...initial,
        x: Math.max(0, Math.min(editor.width - initial.width, initial.x + point.x - start.x)),
        y: Math.max(0, Math.min(editor.height - initial.height, initial.y + point.y - start.y)) };
    } else {
      let left = initial.x, top = initial.y;
      let right = initial.x + initial.width, bottom = initial.y + initial.height;
      if (mode.includes("w")) left = Math.min(right - 20, point.x);
      if (mode.includes("e")) right = Math.max(left + 20, point.x);
      if (mode.includes("n")) top = Math.min(bottom - 20, point.y);
      if (mode.includes("s")) bottom = Math.max(top + 20, point.y);
      editor.box = { x: Math.max(0, left), y: Math.max(0, top),
                     width: Math.min(editor.width, right) - Math.max(0, left),
                     height: Math.min(editor.height, bottom) - Math.max(0, top) };
    }
    renderCropEditorBox();
  });
  window.addEventListener("pointerup", (event) => {
    if (state.cropEditor?.drag?.pointerId === event.pointerId) {
      state.cropEditor.drag = null;
      renderCropEditorBox();
    }
  });
  document.getElementById("crop-editor-accept").addEventListener("click", approveWorkspacePage);
  document.getElementById("crop-editor-discard").addEventListener("click", discardWorkspaceSelection);
  document.getElementById("crop-workspace-page").addEventListener("change", (event) => openCropEditor(Number(event.target.value), null));
  document.getElementById("crop-editor-close").addEventListener("click", closeCropEditor);
  document.getElementById("crop-editor-modal").addEventListener("click", (event) => {
    if (event.target.id === "crop-editor-modal") closeCropEditor();
  });
}

async function approveWorkspacePage() {
  const editor = state.cropEditor;
  if (!editor || state.cropReview.pages[editor.pageNumber - 1].status === "unprepared") return;
  const sourceId = state.cropReview.source_pdf_id;
  const button = document.getElementById("crop-editor-accept");
  button.disabled = true;
  try {
    const existing = state.cropReview.pages[editor.pageNumber - 1].proposals.find((p) => p.id === editor.proposalId);
    if (editor.box && (editor.box.width < 20 || editor.box.height < 20)) return;
    if (editor.box && !existing) {
      state.cropReview = await api(`/api/pdf-import/source-pdfs/${sourceId}/crop-review/pages/${editor.pageNumber}/proposals`,
        { method: "POST", body: JSON.stringify(editor.box) });
    } else if (existing && editor.box) {
      const changed = ["x", "y", "width", "height"].some((key) => existing.crop_box[key] !== editor.box[key]);
      if (changed) {
        state.cropReview = await api(`/api/pdf-import/crop-proposals/${existing.id}/box`,
          { method: "PATCH", body: JSON.stringify(editor.box) });
      } else if (existing.decision === "discarded") {
        state.cropReview = await api(`/api/pdf-import/crop-proposals/${existing.id}`,
          { method: "PATCH", body: JSON.stringify({ decision: "accepted" }) });
      }
    }
    state.cropReview = await api(`/api/pdf-import/source-pdfs/${sourceId}/crop-review/pages/${editor.pageNumber}/accept-all`,
      { method: "POST" });
    renderCropReview();
    const next = state.cropReview.pages.find((page) => page.page_number > editor.pageNumber && !page.confirmed)
      || state.cropReview.pages.find((page) => !page.confirmed);
    if (next) openCropEditor(next.page_number, null);
    else openCropEditor(editor.pageNumber, null);
    toast(`${editor.pageNumber}페이지를 채택했습니다.`);
  } catch (error) {
    toast(`채택 실패: ${error.message}`, true);
  } finally {
    if (button.isConnected) button.disabled = false;
  }
}

async function discardWorkspaceSelection() {
  const editor = state.cropEditor;
  if (!editor?.box) return;
  if (editor.proposalId == null) {
    editor.box = null;
    editor.userDraft = false;
    renderCropEditorBox();
    return;
  }
  try {
    state.cropReview = await api(`/api/pdf-import/crop-proposals/${editor.proposalId}`,
      { method: "PATCH", body: JSON.stringify({ decision: "discarded" }) });
    const page = state.cropReview.pages[editor.pageNumber - 1];
    const next = page.proposals.find((p) => p.decision === "pending")
      || page.proposals.find((p) => p.id !== editor.proposalId && p.decision !== "discarded");
    openCropEditor(editor.pageNumber, next?.id || 0);
    renderCropReview();
  } catch (error) { toast(`버리기 실패: ${error.message}`, true); }
}

async function finalizeCropReview() {
  try {
    const id = state.cropReview.source_pdf_id;
    const result = await api(`/api/pdf-import/source-pdfs/${id}/crop-review/finalize`, { method: "POST" });
    state.cropReview = await api(`/api/pdf-import/source-pdfs/${id}/crop-review`);
    renderCropReview();
    loadPdfImportView();
    toast(`문제 ${result.imported_problem_count}개를 문제함에 등록했습니다.`);
  } catch (e) { toast(`최종 등록 실패: ${e.message}`, true); }
}

/* ---------------- Problems ---------------- */

async function loadProblemsView() {
  await populateSourcePdfFilter();
  await applyProblemFilter();
}

async function populateSourcePdfFilter() {
  const select = document.getElementById("filter-source-pdf");
  const current = select.value;
  try {
    const list = state.sourcePdfs.length ? state.sourcePdfs : await api("/api/pdf-import/source-pdfs");
    state.sourcePdfs = list;
    select.innerHTML =
      `<option value="">전체</option>` +
      list.map((p) => `<option value="${p.source_pdf_id}">${escapeHtml(p.original_filename)}</option>`).join("");
    select.value = current;
  } catch (_) {
    /* non-fatal */
  }
}

async function applyProblemFilter() {
  const tbody = document.getElementById("problems-tbody");
  tbody.innerHTML = `<tr><td colspan="8" class="empty">불러오는 중…</td></tr>`;

  const status = document.getElementById("filter-status").value;
  const sourcePdfId = document.getElementById("filter-source-pdf").value;
  const subject = document.getElementById("filter-subject").value.trim();

  const params = new URLSearchParams({ page_size: "100" });
  if (status) params.set("status", status);
  else params.set("status", ""); // explicit "all"
  if (sourcePdfId) params.set("source_pdf_id", sourcePdfId);
  if (subject) params.set("elective_subject", subject);

  try {
    const list = await api(`/api/problems/?${params.toString()}`);
    state.problemsCache = list;
    if (!list.length) {
      tbody.innerHTML = `<tr><td colspan="8" class="empty">조건에 맞는 문제가 없습니다</td></tr>`;
      return;
    }
    tbody.innerHTML = list
      .map(
        (p) => `
      <tr class="clickable" data-problem-id="${p.id}">
        <td>${p.problem_image_url ? `<img class="thumb" src="${resolveUploadUrl(p.problem_image_url)}" loading="lazy" />` : "-"}</td>
        <td>${p.problem_number ?? "-"}</td>
        <td>${p.source_pdf_id ?? "-"}</td>
        <td>${p.page_number ?? "-"}</td>
        <td>${escapeHtml(p.large_unit || "-")}</td>
        <td>${p.score ?? "-"}</td>
        <td>${statusPill(p.status)}</td>
        <td><button class="btn" data-open-problem="${p.id}">열기</button></td>
      </tr>`
      )
      .join("");

    tbody.querySelectorAll("[data-open-problem]").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        openProblemModal(Number(btn.dataset.openProblem));
      });
    });
    tbody.querySelectorAll("tr.clickable").forEach((row) => {
      row.addEventListener("click", () => openProblemModal(Number(row.dataset.problemId)));
    });
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty">불러오기 실패: ${escapeHtml(e.message)}</td></tr>`;
  }
}

function openProblemModal(id) {
  const problem = state.problemsCache.find((p) => p.id === id);
  if (!problem) return;

  document.getElementById("modal-title").textContent = `문제 #${problem.id} 상세`;
  const body = document.getElementById("modal-body");

  body.innerHTML = `
    <div class="detail-images">
      ${problem.problem_image_url ? `<img src="${resolveUploadUrl(problem.problem_image_url)}" alt="문제 이미지" />` : ""}
      ${problem.page_image_url ? `<img src="${resolveUploadUrl(problem.page_image_url)}" alt="원본 페이지" />` : ""}
    </div>
    <div class="detail-grid">
      <div class="field"><label>큰 단원</label><input type="text" id="f-large-unit" value="${escapeAttr(problem.large_unit)}" /></div>
      <div class="field"><label>세부 단원</label><input type="text" id="f-middle-unit" value="${escapeAttr(problem.middle_unit)}" /></div>
      <div class="field"><label>난이도</label><input type="text" id="f-difficulty" value="${escapeAttr(problem.difficulty)}" /></div>
      <div class="field"><label>배점</label><input type="number" id="f-score" value="${problem.score ?? ""}" /></div>
      <div class="field"><label>태그 (쉼표로 구분)</label><input type="text" id="f-tags" value="${escapeAttr((problem.tags || []).join(", "))}" /></div>
      <div class="field"><label>상태</label>
        <select id="f-status">
          ${["unclassified", "classified", "excluded"].map((s) => `<option value="${s}" ${s === problem.status ? "selected" : ""}>${STATUS_LABEL[s]}</option>`).join("")}
        </select>
      </div>
    </div>
    <div class="field"><label>메모</label><textarea id="f-memo" rows="2">${escapeHtml(problem.memo || "")}</textarea></div>
    <div class="section-block">
      <div class="section-title">📝 객관식 보기 구조</div>
      <div class="result-box choices-box" id="f-choices-box">불러오는 중…</div>
    </div>
    <div class="section-block">
      <div class="section-title">🗂 문제 영역 정보</div>
      <div class="result-box hidden" id="f-vision-result"></div>
    </div>
    <pre class="result-box hidden" id="f-analysis-result"></pre>
    <div class="modal-actions">
      <button class="btn btn-primary" id="f-vision">👁 Claude 비전 인식 (OCR/LaTeX)</button>
      <button class="btn" id="f-analyze">AI 분석 실행 (Mock)</button>
      <div class="right">
        <button class="btn btn-danger" id="f-exclude">제외 처리</button>
        <button class="btn btn-primary" id="f-save">저장</button>
      </div>
    </div>
  `;

  document.getElementById("f-save").addEventListener("click", () => saveProblem(problem.id));
  document.getElementById("f-exclude").addEventListener("click", () => excludeProblem(problem.id));
  document.getElementById("f-analyze").addEventListener("click", () => analyzeProblem(problem.id));
  document.getElementById("f-vision").addEventListener("click", () => runVisionExtraction(problem.id));

  // 읽기 전용 "객관식 보기 구조" 섹션 채우기 (fire-and-forget, 내부 try/catch로 격리)
  loadProblemChoices(problem.id);

  document.getElementById("problem-modal").classList.remove("hidden");
}

/* ---------------- Problem choices (read-only) ---------------- */

async function loadProblemChoices(problemId) {
  const box = document.getElementById("f-choices-box");
  if (!box) return;
  try {
    const result = await api(`/api/problems/${problemId}/choices`);
    const choices = (result && result.choices) || [];
    renderProblemChoices(box, choices);
  } catch (_) {
    // 실패해도 모달의 다른 부분은 정상 유지한다.
    box.classList.remove("choices-empty");
    box.textContent = "보기 정보를 불러오지 못했습니다.";
  }
}

function renderProblemChoices(box, choices) {
  // ProblemChoice 우선. (Problem.choices 컬럼이 없으므로 fallback 대상 없음)
  // choices 가 비어 있으면 "등록된 보기 없음" 빈 상태를 표시한다.
  if (!choices.length) {
    box.classList.add("choices-empty");
    box.textContent = "등록된 객관식 보기가 없습니다.";
    return;
  }
  box.classList.remove("choices-empty");

  const rows = choices
    .slice()
    .sort((a, b) => (a.choice_index ?? 0) - (b.choice_index ?? 0))
    .map((c) => {
      const label = c.choice_label || (c.choice_index != null ? `${c.choice_index}` : "-");
      const body = c.text || c.latex_text || c.normalized_text || "";
      const badges = choiceBadges(c);
      return `<li class="choice-item">`
        + `<span class="choice-label">${escapeHtml(label)}</span>`
        + `<span class="choice-text">${escapeHtml(body) || '<span class="choice-empty-text">(내용 없음)</span>'}</span>`
        + badges
        + `</li>`;
    })
    .join("");

  box.innerHTML = `<ul class="choice-list">${rows}</ul>`;
}

function choiceBadges(c) {
  // 정답 추측 금지: null 이면 배지를 붙이지 않는다.
  const badges = [];
  if (c.is_correct === true) badges.push(`<span class="choice-badge badge-correct">정답</span>`);
  if (c.is_distractor === true) badges.push(`<span class="choice-badge badge-distractor">오답지</span>`);
  if (c.is_correct == null && c.is_distractor == null) {
    badges.push(`<span class="choice-badge badge-unknown">미정</span>`);
  }
  return badges.length ? `<span class="choice-badges">${badges.join("")}</span>` : "";
}

function closeProblemModal() {
  document.getElementById("problem-modal").classList.add("hidden");
}

async function saveProblem(id) {
  const payload = {
    large_unit: valueOrNull("f-large-unit"),
    middle_unit: valueOrNull("f-middle-unit"),
    difficulty: valueOrNull("f-difficulty"),
    score: document.getElementById("f-score").value ? Number(document.getElementById("f-score").value) : null,
    tags: document
      .getElementById("f-tags")
      .value.split(",")
      .map((t) => t.trim())
      .filter(Boolean),
    memo: valueOrNull("f-memo"),
    status: document.getElementById("f-status").value,
  };
  try {
    await api(`/api/problems/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
    toast("저장되었습니다");
    closeProblemModal();
    applyProblemFilter();
  } catch (e) {
    toast(`저장 실패: ${e.message}`, true);
  }
}

async function excludeProblem(id) {
  try {
    await api(`/api/problems/${id}`, { method: "DELETE" });
    toast("문제를 제외 처리했습니다");
    closeProblemModal();
    applyProblemFilter();
  } catch (e) {
    toast(`제외 처리 실패: ${e.message}`, true);
  }
}

async function analyzeProblem(id) {
  const box = document.getElementById("f-analysis-result");
  box.classList.remove("hidden");
  box.textContent = "분석 실행 중…";
  try {
    const result = await api(`/api/problems/${id}/analyze`, { method: "POST" });
    box.textContent = JSON.stringify(result, null, 2);
  } catch (e) {
    box.textContent = `분석 실패: ${e.message}`;
  }
}

function valueOrNull(id) {
  const v = document.getElementById(id).value;
  return v.trim() === "" ? null : v;
}

/* ---------------- Solution modules ---------------- */

async function loadSolutionModulesView() {
  const tbody = document.getElementById("sm-tbody");
  tbody.innerHTML = `<tr><td colspan="5" class="empty">불러오는 중…</td></tr>`;
  try {
    const list = await api("/solution-modules/");
    state.solutionModules = list;
    if (!list.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="empty">등록된 소유형 모듈이 없습니다</td></tr>`;
      return;
    }
    tbody.innerHTML = list
      .map(
        (m) => `
      <tr>
        <td>${escapeHtml(m.module_id)}</td>
        <td>${escapeHtml(m.name)}</td>
        <td>${escapeHtml(m.large_unit || "-")}</td>
        <td>${statusPill(m.status)}</td>
        <td>${m.status !== "verified" ? `<button class="btn" data-verify="${m.module_id}">검증</button>` : ""}</td>
      </tr>`
      )
      .join("");

    tbody.querySelectorAll("[data-verify]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await api(`/solution-modules/${btn.dataset.verify}/verify`, { method: "PATCH" });
          toast("모듈을 검증 완료로 표시했습니다");
          loadSolutionModulesView();
        } catch (e) {
          toast(`검증 실패: ${e.message}`, true);
        }
      });
    });
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5" class="empty">불러오기 실패: ${escapeHtml(e.message)}</td></tr>`;
  }
}

function setupSolutionModuleForm() {
  document.getElementById("sm-create-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const desc = document.getElementById("sm-description").value.trim();
    const resultEl = document.getElementById("sm-create-result");
    if (!desc) return;
    resultEl.textContent = "초안 생성 중…";
    try {
      const result = await api(`/solution-modules/?user_description=${encodeURIComponent(desc)}`, { method: "POST" });
      resultEl.textContent = `초안 생성됨: ${result.module.module_id} (${result.module.name})`;
      document.getElementById("sm-description").value = "";
      toast("소유형 초안이 생성되었습니다 (draft 상태)");
      loadSolutionModulesView();
    } catch (e) {
      resultEl.textContent = `실패: ${e.message}`;
    }
  });
}

/* ---------------- Concept modules ---------------- */

async function loadConceptModulesView() {
  const tbody = document.getElementById("cm-tbody");
  tbody.innerHTML = `<tr><td colspan="4" class="empty">불러오는 중…</td></tr>`;
  try {
    const list = await api("/concept-modules/");
    if (!list.length) {
      tbody.innerHTML = `<tr><td colspan="4" class="empty">등록된 개념 모듈이 없습니다</td></tr>`;
      return;
    }
    tbody.innerHTML = list
      .map(
        (c) => `
      <tr>
        <td>${escapeHtml(c.concept_id)}</td>
        <td>${escapeHtml(c.name)}</td>
        <td>${escapeHtml(c.large_unit || "-")}</td>
        <td>${escapeHtml(c.formula_latex || "-")}</td>
      </tr>`
      )
      .join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" class="empty">불러오기 실패: ${escapeHtml(e.message)}</td></tr>`;
  }
}

function setupConceptModuleForm() {
  document.getElementById("cm-create-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const payload = {
      concept_id: document.getElementById("cm-concept-id").value.trim(),
      name: document.getElementById("cm-name").value.trim(),
      large_unit: valueOrNull("cm-large-unit"),
      middle_unit: valueOrNull("cm-middle-unit"),
      formula_latex: valueOrNull("cm-formula"),
      description: valueOrNull("cm-description"),
    };
    try {
      await api("/concept-modules/", { method: "POST", body: JSON.stringify(payload) });
      toast("개념 모듈이 추가되었습니다");
      ev.target.reset();
      loadConceptModulesView();
    } catch (e) {
      toast(`추가 실패: ${e.message}`, true);
    }
  });
}

/* ---------------- Type combinations ---------------- */

async function loadTypeCombinationsView() {
  const tbody = document.getElementById("tc-tbody");
  tbody.innerHTML = `<tr><td colspan="4" class="empty">불러오는 중…</td></tr>`;
  try {
    const list = await api("/type-combinations/");
    state.typeCombinations = list;
    if (!list.length) {
      tbody.innerHTML = `<tr><td colspan="4" class="empty">등록된 유형 조합이 없습니다</td></tr>`;
      return;
    }
    tbody.innerHTML = list
      .map(
        (c) => `
      <tr>
        <td>${escapeHtml(c.combination_id)}</td>
        <td>${escapeHtml(c.name)}</td>
        <td>${escapeHtml((c.module_sequence || []).join(" → "))}</td>
        <td>${statusPill(c.status)}</td>
      </tr>`
      )
      .join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="4" class="empty">불러오기 실패: ${escapeHtml(e.message)}</td></tr>`;
  }
}

function setupTypeCombinationForm() {
  document.getElementById("tc-create-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const payload = {
      combination_id: document.getElementById("tc-combination-id").value.trim(),
      name: document.getElementById("tc-name").value.trim(),
      module_sequence: document
        .getElementById("tc-module-sequence")
        .value.split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      connection_rule: valueOrNull("tc-connection-rule"),
      generation_strategy: valueOrNull("tc-generation-strategy"),
      difficulty_level: valueOrNull("tc-difficulty"),
    };
    try {
      await api("/type-combinations/", { method: "POST", body: JSON.stringify(payload) });
      toast("유형 조합이 추가되었습니다");
      ev.target.reset();
      loadTypeCombinationsView();
    } catch (e) {
      toast(`추가 실패: ${e.message}`, true);
    }
  });
}

/* ---------------- Analyze (Mock) ---------------- */

function setupAnalyzeForm() {
  document.getElementById("analyze-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const text = document.getElementById("analyze-text").value.trim();
    const resultEl = document.getElementById("analyze-result");
    resultEl.textContent = "분석 중…";
    try {
      const result = await api("/analysis/", { method: "POST", body: JSON.stringify({ problem_text: text }) });
      resultEl.textContent = JSON.stringify(result, null, 2);
    } catch (e) {
      resultEl.textContent = `실패: ${e.message}`;
    }
  });
}

/* ---------------- Generate (Mock) ---------------- */

async function loadGenerateView() {
  try {
    const [modules, combos] = await Promise.all([
      state.solutionModules.length ? Promise.resolve(state.solutionModules) : api("/solution-modules/"),
      state.typeCombinations.length ? Promise.resolve(state.typeCombinations) : api("/type-combinations/"),
    ]);
    state.solutionModules = modules;
    state.typeCombinations = combos;

    const moduleSelect = document.getElementById("gen-modules");
    moduleSelect.innerHTML = modules
      .map((m) => `<option value="${m.module_id}">${escapeHtml(m.module_id)} — ${escapeHtml(m.name)}</option>`)
      .join("");

    const comboSelect = document.getElementById("gen-combination");
    comboSelect.innerHTML =
      `<option value="">유형 조합 선택 안 함</option>` +
      combos.map((c) => `<option value="${c.combination_id}">${escapeHtml(c.combination_id)} — ${escapeHtml(c.name)}</option>`).join("");
  } catch (e) {
    toast(`생성 화면 준비 실패: ${e.message}`, true);
  }
}

function setupGenerateForm() {
  document.getElementById("generate-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const moduleSelect = document.getElementById("gen-modules");
    const selectedModules = Array.from(moduleSelect.selectedOptions).map((o) => o.value);
    if (!selectedModules.length) {
      toast("소유형 모듈을 1개 이상 선택하세요", true);
      return;
    }
    const payload = {
      selected_module_ids: selectedModules,
      selected_combination_id: document.getElementById("gen-combination").value || null,
      difficulty_level: document.getElementById("gen-difficulty").value || "medium",
      generation_goal: document.getElementById("gen-goal").value.trim(),
    };
    const resultEl = document.getElementById("generate-result");
    resultEl.textContent = "생성 중…";
    try {
      const result = await api("/generate/problem", { method: "POST", body: JSON.stringify(payload) });
      resultEl.textContent = JSON.stringify(result, null, 2);
    } catch (e) {
      resultEl.textContent = `실패: ${e.message}`;
    }
  });
}

/* ---------------- utils ---------------- */

function resolveUploadUrl(url) {
  // The backend sometimes returns image paths without a leading slash
  // (e.g. "uploads/problems/..."), which resolves relative to /admin/.
  // Normalize to an absolute path so images load regardless of API quirks.
  if (!url) return url;
  if (/^https?:\/\//i.test(url) || url.startsWith("/")) return url;
  return `/${url}`;
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
function escapeAttr(str) {
  return escapeHtml(str).replace(/"/g, "&quot;");
}
function formatDate(iso) {
  if (!iso) return "-";
  try {
    const d = new Date(iso);
    return d.toLocaleString("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  } catch (_) {
    return iso;
  }
}

async function checkConnection() {
  const el = document.getElementById("conn-status");
  try {
    await api("/");
    el.textContent = "서버 연결됨";
    el.classList.add("ok");
    el.classList.remove("err");
  } catch (_) {
    el.textContent = "서버에 연결할 수 없습니다";
    el.classList.add("err");
    el.classList.remove("ok");
  }
}

/* ---------------- init ---------------- */

function init() {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });
  document.getElementById("modal-close").addEventListener("click", closeProblemModal);
  document.getElementById("problem-modal").addEventListener("click", (ev) => {
    if (ev.target.id === "problem-modal") closeProblemModal();
  });
  document.getElementById("crop-finalize").addEventListener("click", finalizeCropReview);
  document.getElementById("crop-review-open").addEventListener("click", () => {
    if (state.cropReview) openCropReview(state.cropReview.source_pdf_id);
  });
  setupCropEditor();

  document.getElementById("filter-apply").addEventListener("click", applyProblemFilter);

  setupUploadForm();
  setupSolutionModuleForm();
  setupConceptModuleForm();
  setupTypeCombinationForm();
  setupAnalyzeForm();
  setupGenerateForm();

  checkConnection();

  const initial = location.hash ? location.hash.slice(1) : "dashboard";
  switchView(VIEW_TITLES[initial] ? initial : "dashboard");
}

document.addEventListener("DOMContentLoaded", init);


async function runVisionExtraction(id) {
  const box = document.getElementById("f-vision-result");
  box.classList.remove("hidden");
  box.textContent = "Claude Vision running...";
  try {
    const result = await api(`/api/problems/${id}/extract-regions`, { method: "POST" });
    renderVisionResult(box, result);
    toast(`OK: ${result.regions.length} regions`);
  } catch (e) {
    box.textContent = `FAILED: ${e.message}`;
    toast("Claude Vision failed", true);
  }
}

function renderVisionResult(box, result) {
  const regions = (result && result.regions) || [];
  if (!regions.length) {
    box.textContent = "No regions detected.";
    return;
  }
  box.innerHTML = regions.map((r) => {
    const items = (r.items || []).map((it) =>
      `<li><b>${escapeHtml(it.label)}</b> ${escapeHtml(it.latex || it.text || (it.image_path ? "[image]" : ""))}</li>`
    ).join("");
    const text = r.latex_text || r.ocr_text || "";
    const conf = r.confidence != null ? ` · ${Math.round(r.confidence * 100)}%` : "";
    return `<div class="vision-region">`
      + `<div class="vision-region-head">#${r.order_index} · ${escapeHtml(r.region_type)}${conf}</div>`
      + (text ? `<div class="vision-region-text">${escapeHtml(text)}</div>` : "")
      + (r.image_path ? `<div class="vision-region-img">[img] ${escapeHtml(r.image_path)}</div>` : "")
      + (items ? `<ul class="vision-items">${items}</ul>` : "")
      + `</div>`;
  }).join("");
}
