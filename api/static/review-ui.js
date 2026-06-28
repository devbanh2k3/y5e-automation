const state = {
  reviews: [],
  selectedReview: null,
};

const els = {
  refreshButton: document.querySelector("#refreshButton"),
  statusFilter: document.querySelector("#statusFilter"),
  reviewList: document.querySelector("#reviewList"),
  reviewStatus: document.querySelector("#reviewStatus"),
  reviewTitle: document.querySelector("#reviewTitle"),
  reviewMeta: document.querySelector("#reviewMeta"),
  videoPreview: document.querySelector("#videoPreview"),
  approveButton: document.querySelector("#approveButton"),
  rejectButton: document.querySelector("#rejectButton"),
  regenerateButton: document.querySelector("#regenerateButton"),
  rerenderInput: document.querySelector("#rerenderInput"),
  notesInput: document.querySelector("#notesInput"),
  reasonInput: document.querySelector("#reasonInput"),
  scenesInput: document.querySelector("#scenesInput"),
  selectedMetadata: document.querySelector("#selectedMetadata"),
  titleVariants: document.querySelector("#titleVariants"),
  descriptionVariants: document.querySelector("#descriptionVariants"),
  metadataTags: document.querySelector("#metadataTags"),
  thumbnailTextSuggestions: document.querySelector("#thumbnailTextSuggestions"),
  qualityGate: document.querySelector("#qualityGate"),
  regenerateCommand: document.querySelector("#regenerateCommand"),
  sceneList: document.querySelector("#sceneList"),
};

function text(value, fallback = "") {
  return value === undefined || value === null || value === "" ? fallback : String(value);
}

function sceneIndexes() {
  return els.scenesInput.value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => Number.parseInt(item, 10))
    .filter((item) => Number.isInteger(item) && item >= 0);
}

function imageForScene(review, index) {
  const items = review.image_verification_contract?.items || [];
  return items.find((item) => item.scene_index === index) || {};
}

function renderReviewList() {
  els.reviewList.innerHTML = "";
  if (!state.reviews.length) {
    els.reviewList.innerHTML = '<p class="meta">No reviews found.</p>';
    return;
  }

  for (const review of state.reviews) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `review-item ${state.selectedReview?.review_id === review.review_id ? "active" : ""}`;
    button.innerHTML = `
      <div class="review-item-title">${text(review.youtube?.title, "Untitled")}</div>
      <div class="review-item-meta">${text(review.status)} · ${text(review.created_at)}</div>
    `;
    button.addEventListener("click", () => loadReview(review.review_id));
    els.reviewList.appendChild(button);
  }
}

function renderQualityGate(review) {
  const gate = review.quality_gate || {};
  const checks = gate.checks || gate.items || [];
  const summary = [
    ["Status", text(gate.status, "unknown")],
    ["Passed", text(gate.passed_count, "n/a")],
    ["Failed", text(gate.failed_count, "n/a")],
  ];

  els.qualityGate.innerHTML = summary
    .map(([key, value]) => `<div><strong>${key}:</strong> ${value}</div>`)
    .join("");

  if (Array.isArray(checks) && checks.length) {
    els.qualityGate.innerHTML += checks
      .slice(0, 8)
      .map((check) => `<div><strong>${text(check.name, "check")}:</strong> ${text(check.status || check.passed)}</div>`)
      .join("");
  }
}

function renderTags(container, values) {
  container.innerHTML = "";
  if (!Array.isArray(values) || !values.length) {
    container.innerHTML = '<p class="meta">No values.</p>';
    return;
  }
  for (const value of values) {
    const item = document.createElement("span");
    item.className = "tag";
    item.textContent = text(value);
    container.appendChild(item);
  }
}

function renderMetadata(review) {
  const variants = review.metadata_variants || {};
  const selected = review.selected_metadata || variants.selected_metadata || {};
  const titleVariants = Array.isArray(variants.title_variants) ? variants.title_variants : [];
  const descriptionVariants = Array.isArray(variants.description_variants)
    ? variants.description_variants
    : [];

  els.selectedMetadata.innerHTML = `
    <div><strong>Selected title:</strong> ${text(selected.title || review.youtube?.title, "n/a")}</div>
    <div><strong>Description:</strong> ${text(selected.description || review.youtube?.description, "n/a")}</div>
    <div><strong>Trend angle:</strong> ${text(variants.trend_angle, "n/a")}</div>
  `;

  els.titleVariants.innerHTML = titleVariants.length
    ? titleVariants
        .map(
          (item, index) => `
            <div class="metadata-item">
              <span>${index + 1}. ${text(item.title)}</span>
              <strong>${text(item.score_total, "n/a")}</strong>
            </div>
          `,
        )
        .join("")
    : '<p class="meta">No title variants.</p>';

  els.descriptionVariants.innerHTML = descriptionVariants.length
    ? descriptionVariants
        .map((item, index) => `<div class="metadata-item">${index + 1}. ${text(item)}</div>`)
        .join("")
    : '<p class="meta">No description variants.</p>';

  renderTags(els.metadataTags, variants.tags || selected.tags || review.youtube?.tags || []);
  renderTags(els.thumbnailTextSuggestions, variants.thumbnail_text_suggestions || []);
}

function renderScenes(review) {
  const scenes = review.content_contract?.scenes || [];
  els.sceneList.innerHTML = "";
  if (!scenes.length) {
    els.sceneList.innerHTML = '<p class="meta">No scenes in this review.</p>';
    return;
  }

  scenes.forEach((scene, index) => {
    const image = imageForScene(review, index);
    const imageUrl = image.local_path ? `/api/reviews/${review.review_id}/images/${index}` : "";
    const card = document.createElement("article");
    card.className = "scene-card";
    card.innerHTML = `
      ${imageUrl ? `<img src="${imageUrl}" alt="${text(scene.title, `Scene ${index}`)}" />` : ""}
      <div class="scene-body">
        <div class="scene-title">${index}. ${text(scene.title, "Untitled scene")}</div>
        <div><strong>${text(scene.metricLabel, "Metric")}:</strong> ${text(scene.metricValue || scene.factValue || scene.caption)}</div>
        <div>${text(scene.voiceover)}</div>
        <div class="source"><strong>Source:</strong> ${text(image.source_url || image.image_url, "n/a")}</div>
        <div class="source"><strong>License:</strong> ${text(image.license, "n/a")}</div>
        <div class="source"><strong>Attribution:</strong> ${text(image.attribution, "n/a")}</div>
      </div>
    `;
    els.sceneList.appendChild(card);
  });
}

function renderReview(review) {
  state.selectedReview = review;
  els.reviewStatus.textContent = text(review.status, "unknown");
  els.reviewTitle.textContent = text(review.youtube?.title || review.content_contract?.title, "Untitled");
  els.reviewMeta.textContent = `Review ${review.review_id} · Topic ${text(review.video?.topic_id, "n/a")}`;
  els.videoPreview.src = `/api/reviews/${review.review_id}/video`;
  els.notesInput.value = "";
  els.scenesInput.value = "";
  els.regenerateCommand.textContent =
    `python3 scripts/regenerate_scene.py ${review.review_id} --scene <scene_index> --reason wrong_image`;
  renderMetadata(review);
  renderQualityGate(review);
  renderScenes(review);
  renderReviewList();
}

async function loadReviews() {
  const status = els.statusFilter.value;
  const query = status ? `?status=${encodeURIComponent(status)}&limit=50` : "?limit=50";
  const response = await fetch(`/api/reviews${query}`);
  if (!response.ok) throw new Error(`Failed to load reviews: ${response.status}`);
  const payload = await response.json();
  state.reviews = payload.reviews || [];
  renderReviewList();
  if (state.reviews.length) {
    await loadReview(state.reviews[0].review_id);
  }
}

async function loadReview(reviewId) {
  const response = await fetch(`/api/reviews/${reviewId}`);
  if (!response.ok) throw new Error(`Failed to load review: ${response.status}`);
  renderReview(await response.json());
}

async function transitionReview(action) {
  if (!state.selectedReview) return;
  const body = {
    notes: els.notesInput.value,
  };
  if (action === "reject") {
    body.reason = els.reasonInput.value || "other";
    body.scenes = sceneIndexes();
  }

  const response = await fetch(`/api/reviews/${state.selectedReview.review_id}/${action}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    alert(payload.detail || `Failed to ${action} review`);
    return;
  }
  await loadReviews();
}

async function regenerateSelectedScene() {
  if (!state.selectedReview) return;
  const scenes = sceneIndexes();
  if (scenes.length !== 1) {
    alert("Enter exactly one scene index to regenerate.");
    return;
  }

  els.regenerateButton.disabled = true;
  els.regenerateButton.textContent = "Regenerating...";
  try {
    const response = await fetch(`/api/reviews/${state.selectedReview.review_id}/regenerate-scene`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        scene: scenes[0],
        reason: "wrong_image",
        rerender: els.rerenderInput.checked,
      }),
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      alert(payload.detail || "Failed to regenerate scene");
      return;
    }
    const updated = await response.json();
    renderReview(updated);
  } finally {
    els.regenerateButton.disabled = false;
    els.regenerateButton.textContent = "Regenerate Scene";
  }
}

els.refreshButton.addEventListener("click", () => loadReviews().catch((error) => alert(error.message)));
els.statusFilter.addEventListener("change", () => loadReviews().catch((error) => alert(error.message)));
els.approveButton.addEventListener("click", () => transitionReview("approve"));
els.rejectButton.addEventListener("click", () => transitionReview("reject"));
els.regenerateButton.addEventListener("click", () => regenerateSelectedScene());

loadReviews().catch((error) => {
  els.reviewList.innerHTML = `<p class="meta">${error.message}</p>`;
});
