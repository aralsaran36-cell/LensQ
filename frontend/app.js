(() => {
  "use strict";

  // Keep in sync with .env: MAX_FILE_SIZE_MB, MIN/MAX_QUESTION_LENGTH
  const MAX_BYTES = 5 * 1024 * 1024;
  const MAX_DIM = 2048;
  const MIN_Q = 3;
  const MAX_Q = 500;
  const TIMEOUT_MS = 120000;

  const $ = (id) => document.getElementById(id);
  const el = {
    btnUpload: $("btn-upload"), btnCamera: $("btn-camera"),
    fileInput: $("file-input"), cameraFallback: $("camera-fallback"),
    cameraPanel: $("camera-panel"), video: $("video"),
    btnCapture: $("btn-capture"), btnCancelCamera: $("btn-cancel-camera"),
    previewPanel: $("preview-panel"), preview: $("preview"), btnClear: $("btn-clear"),
    askPanel: $("ask-panel"), question: $("question"), btnAsk: $("btn-ask"),
    status: $("status"), error: $("error"), errorText: $("error-text"),
    btnRetry: $("btn-retry"), thread: $("thread"),
    avatarTpl: $("tpl-avatar"),
  };

  // Everything lives in memory only. Nothing is written to localStorage/cookies.
  const state = {
    blob: null,
    previewUrl: null,
    sessionId: null,
    imageSent: false,
    stream: null,
    busy: false,
    lastQuestion: null,
  };

  // ---------- small UI helpers ----------
  function setStatus(text) {
    el.status.hidden = !text;
    el.status.textContent = text || "";
  }
  function clearError() {
    el.error.hidden = true;
    el.btnRetry.hidden = true;
  }
  function showError(message, canRetry = false) {
    el.errorText.textContent = message;
    el.btnRetry.hidden = !canRetry;
    el.error.hidden = false;
  }
  function setBusy(busy) {
    state.busy = busy;
    el.btnAsk.disabled = busy;
    el.btnRetry.disabled = busy;
    el.btnUpload.disabled = busy;
    el.btnCamera.disabled = busy;
    el.btnClear.disabled = busy;
  }

  // ---------- image preparation (client side) ----------
  function canvasToJpeg(canvas) {
    const tryQuality = (q) =>
      new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", q));
    return (async () => {
      for (const q of [0.85, 0.7, 0.5]) {
        const blob = await tryQuality(q);
        if (blob && blob.size <= MAX_BYTES) return blob;
      }
      throw new Error("TOO_LARGE");
    })();
  }

  function drawScaled(source, width, height) {
    const scale = Math.min(1, MAX_DIM / Math.max(width, height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    canvas.getContext("2d").drawImage(source, 0, 0, canvas.width, canvas.height);
    return canvas;
  }

  async function prepareFile(file) {
    try {
      const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
      const canvas = drawScaled(bitmap, bitmap.width, bitmap.height);
      bitmap.close();
      return await canvasToJpeg(canvas); // JPEG re-encode also strips EXIF/GPS
    } catch (err) {
      if (err.message === "TOO_LARGE") throw err;
      // Browser could not decode it (for example HEIC on Chrome).
      // Send the original file, the server converts it. Size is still limited.
      if (file.size <= MAX_BYTES) return file;
      throw new Error("TOO_LARGE");
    }
  }

  // ---------- image selection ----------
  function resetThread() {
    el.thread.replaceChildren();
  }

  function setImage(blob) {
    if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
    state.blob = blob;
    state.previewUrl = URL.createObjectURL(blob);
    state.imageSent = false; // the next question uploads this image (replaces the old one)
    el.preview.src = state.previewUrl;
    el.previewPanel.hidden = false;
    el.askPanel.hidden = false;
    resetThread();
    clearError();
    setStatus("");
    el.question.focus();
  }

  async function handleFile(file) {
    if (!file) return;
    clearError();
    if (!file.type.startsWith("image/")) {
      showError("Please choose an image file.");
      return;
    }
    setStatus("Preparing image...");
    try {
      setImage(await prepareFile(file));
    } catch (err) {
      showError("This image is too large. Please use a smaller photo (max 5 MB).");
    } finally {
      setStatus("");
    }
  }

  function endSessionOnServer() {
    if (!state.sessionId) return;
    const data = new FormData();
    data.append("session_id", state.sessionId);
    // sendBeacon survives tab close
    if (!(navigator.sendBeacon && navigator.sendBeacon("/session/end", data))) {
      fetch("/session/end", { method: "POST", body: data, keepalive: true }).catch(() => {});
    }
  }

  function clearImage() {
    endSessionOnServer();
    if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
    state.blob = null;
    state.previewUrl = null;
    state.sessionId = null;
    state.imageSent = false;
    state.lastQuestion = null;
    el.preview.removeAttribute("src");
    el.previewPanel.hidden = true;
    el.askPanel.hidden = true;
    el.question.value = "";
    resetThread();
    clearError();
    setStatus("");
  }

  // ---------- camera ----------
  function stopCamera() {
    if (state.stream) {
      state.stream.getTracks().forEach((t) => t.stop());
      state.stream = null;
    }
    el.video.srcObject = null;
    el.cameraPanel.hidden = true;
  }

  async function openCamera() {
    clearError();
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      // Plain http (not localhost) has no camera API. Use the phone's camera app instead.
      el.cameraFallback.click();
      return;
    }
    try {
      state.stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } },
        audio: false,
      });
      el.video.srcObject = state.stream;
      el.cameraPanel.hidden = false;
    } catch (err) {
      if (err.name === "NotAllowedError" || err.name === "SecurityError") {
        showError("Camera permission was denied. Allow camera access in your browser settings, or use Upload Image.");
      } else if (err.name === "NotFoundError" || err.name === "OverconstrainedError") {
        showError("No camera was found on this device. Use Upload Image instead.");
      } else {
        showError("Could not open the camera. Use Upload Image instead.");
      }
    }
  }

  async function capture() {
    const w = el.video.videoWidth;
    const h = el.video.videoHeight;
    if (!w || !h) {
      showError("Camera is not ready yet. Please try again.");
      return;
    }
    try {
      const blob = await canvasToJpeg(drawScaled(el.video, w, h));
      stopCamera();
      setImage(blob);
    } catch (err) {
      showError("Could not capture the photo. Please try again.");
    }
  }

  // ---------- asking ----------
  async function send(question, withImage) {
    const form = new FormData();
    form.append("question", question);
    if (state.sessionId) form.append("session_id", state.sessionId);
    if (withImage) form.append("image", state.blob, "photo.jpg");

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const res = await fetch("/analyze", { method: "POST", body: form, signal: controller.signal });
      let data = null;
      try { data = await res.json(); } catch (e) { /* non-JSON error page */ }
      return { ok: res.ok, data };
    } finally {
      clearTimeout(timer);
    }
  }

  function addTurn(question, answer) {
    const turn = document.createElement("div");
    turn.className = "turn";

    const q = document.createElement("div");
    q.className = "q";
    q.textContent = question; // textContent only: model output is never inserted as HTML

    const row = document.createElement("div");
    row.className = "answer-row";

    const a = document.createElement("div");
    a.className = "a";
    const label = document.createElement("span");
    label.className = "label";
    label.textContent = "LensQ";
    const text = document.createElement("span");
    text.className = "text";
    text.textContent = answer; // textContent only
    a.append(label, text);

    if (el.avatarTpl && el.avatarTpl.content.firstElementChild) {
      row.append(el.avatarTpl.content.firstElementChild.cloneNode(true));
    }
    row.append(a);

    turn.append(q, row);
    el.thread.append(turn);
    turn.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async function ask(question) {
    if (state.busy) return;
    clearError();

    question = question.trim();
    if (!state.blob) { showError("Please upload or capture an image first."); return; }
    if (question.length < MIN_Q) { showError(`Please type a question (at least ${MIN_Q} characters).`); return; }
    if (question.length > MAX_Q) { showError(`Question is too long (max ${MAX_Q} characters).`); return; }

    state.lastQuestion = question;
    setBusy(true);
    setStatus("Analyzing image...");
    try {
      const needImage = !state.sessionId || !state.imageSent;
      let result = await send(question, needImage);

      // Session expired or server restarted: re-upload automatically (image is still in this tab)
      if (!result.ok && result.data && result.data.error_code === "SESSION_EXPIRED" && !needImage) {
        state.sessionId = null;
        state.imageSent = false;
        result = await send(question, true);
      }

      if (result.ok && result.data && result.data.answer) {
        state.sessionId = result.data.session_id;
        state.imageSent = true;
        addTurn(question, result.data.answer);
        el.question.value = "";
        state.lastQuestion = null;
      } else {
        const d = result.data || {};
        showError(d.message || "Something went wrong. Please try again.", d.retry !== false);
      }
    } catch (err) {
      if (err.name === "AbortError") {
        showError("The request took too long. Please try again.", true);
      } else {
        showError("Network problem. Check your connection and try again.", true);
      }
    } finally {
      setBusy(false);
      setStatus("");
    }
  }

  // ---------- events ----------
  el.btnUpload.addEventListener("click", () => el.fileInput.click());
  el.btnCamera.addEventListener("click", openCamera);
  el.fileInput.addEventListener("change", () => {
    handleFile(el.fileInput.files[0]);
    el.fileInput.value = "";
  });
  el.cameraFallback.addEventListener("change", () => {
    handleFile(el.cameraFallback.files[0]);
    el.cameraFallback.value = "";
  });
  el.btnCapture.addEventListener("click", capture);
  el.btnCancelCamera.addEventListener("click", stopCamera);
  el.btnClear.addEventListener("click", clearImage);
  el.btnAsk.addEventListener("click", () => ask(el.question.value));
  el.question.addEventListener("keydown", (e) => {
    // Ctrl/Cmd + Enter sends. Plain Enter stays a new line (good for phones).
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      ask(el.question.value);
    }
  });
  el.btnRetry.addEventListener("click", () => ask(state.lastQuestion || el.question.value));
  window.addEventListener("pagehide", () => {
    stopCamera();
    endSessionOnServer();
  });
})();