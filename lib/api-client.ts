export type ProjectAsset = {
  id: string;
  sequence_no: number;
  role: string;
  parent_asset_id?: string | null;
  archived?: boolean;
  original_name: string;
  mime_type: string;
  file_size: number;
  sha256: string;
  created_at: string;
};

export type Project = {
  id: string;
  owner_id: string;
  name: string;
  status: string;
  current_stage: string;
  archived?: boolean;
  created_at: string;
  updated_at: string;
  assets: ProjectAsset[];
};

export type GeneratedPattern = {
  id: string;
  project_id: string;
  source_asset_id: string;
  board_layout: string;
  color_mode: string;
  palette_version: string;
  pattern: {
    width: number;
    height: number;
    cells: Array<{ x: number; y: number; colorCode: string; colorValue: string; boardId: string }>;
    palette: Array<{ code: string; value: string; count: number }>;
    statistics: {
      totalBeads: number; colorCount: number; physicalWidthMm: number; physicalHeightMm: number;
      qualityScore?: number; qualityLevel?: string; recommendedMinimumBoard?: string; qualityWarnings?: string[];
      semanticPlanning?: {
        used?: boolean; fallback?: boolean; model?: string; assessment?: string;
        fallbackReason?: string; fallbackMessage?: string; cacheHit?: boolean; identityPriorities?: string[];
      };
    };
  };
};

export type PatternVersion = {
  id: string; version_no: number; name: string; note: string;
  source_revision: number; created_at: string; pattern?: GeneratedPattern["pattern"];
};

export type StageVersion = { id: string; stage: string; version_no: number; name: string; created_at: string; snapshot?: Record<string, unknown> };

export type PatternIssue = {
  id: string; type: string; severity: "warning" | "info"; title: string; message: string;
  coordinates: Array<{ x: number; y: number }>; colorCodes: string[]; metric?: number;
};

export type PatternExport = {
  filename: string; revision: number; board_count: number; file_count: number;
  total_beads: number; color_count: number; size_bytes: number;
  download_url: string; manifest: Record<string, unknown>;
};

export type BeadColor = { code: string; value: string };

export type BatchItem = {
  id: string; sequence_no: number; source_asset_id: string;
  status: string; pattern_id?: string; error_code?: string;
  confirmed: boolean; attempts: number;
};

export type BatchJob = {
  id: string; project_id: string; status: string; board_layout: string;
  color_mode: string; created_at: string; updated_at: string;
  items: BatchItem[]; summary: Record<string, number>;
};

export type TwoDCandidate = {
  asset: ProjectAsset;
  source_asset_id: string;
  variant: "simplified" | "standard" | "rich";
  label: string;
  detail: string;
  recommended: boolean;
  quality: { score?: number; coverage?: number; complexBackground?: boolean; touchesEdge?: boolean; subjectBounds?: {left:number;top:number;right:number;bottom:number} | null; subjectMargins?: {left:number|null;top:number|null;right:number|null;bottom:number|null}; edgeSafetyMargin?: number; confirmable?: boolean; generationMode?: string; model?: string; complexityScore?: number; complexityLevel?: string; recommendedVariant?: string; recommendedBoard?: string; route?: string; selectedStrategy?: string; warnings?: Array<{code: string; message: string}> };
};

export type ImageModelStatus = {
  provider: string; model: string; configured: boolean; generationMode: string;
  candidateCount: number; candidateCountOptions?: number[];
  variants?: Array<"simplified" | "standard" | "rich">; keyStorage: string;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  providerCode?: string;
  providerMessage?: string;
  requestId?: string;
  diagnostics?: { trace_id?: string; operation?: string; elapsed_ms?: number; max_retries?: number; connection_stage?: string; transport?: { proxy_configured?: boolean; proxy_entries?: string[]; no_proxy_configured?: boolean }; exception_chain?: Array<{type?: string; message?: string}>; input?: { original_size?: string; prepared_size?: string; format?: string; bytes?: number; transparent_pixel_ratio?: number; background?: string; sdk_attempts_max?: number } };

  constructor(code: string, detail?: Record<string, unknown>) {
    super(code);
    this.name = "ApiError";
    this.providerCode = typeof detail?.provider_code === "string" ? detail.provider_code : undefined;
    this.providerMessage = typeof detail?.provider_message === "string" ? detail.provider_message : undefined;
    this.requestId = typeof detail?.request_id === "string" ? detail.request_id : undefined;
    this.diagnostics = typeof detail?.diagnostics === "object" && detail?.diagnostics !== null
      ? detail.diagnostics as ApiError["diagnostics"] : undefined;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const code = payload?.detail?.code ?? `HTTP_${response.status}`;
    throw new ApiError(code, payload?.detail);
  }
  return response.json() as Promise<T>;
}

export const api = {
  getImageModelStatus() {
    return request<ImageModelStatus>("/api/v1/model-status");
  },
  listProjects(archived = false) {
    return request<{ items: Project[]; total: number }>(`/api/v1/projects?archived=${archived}`);
  },
  createProject(name: string) {
    return request<Project>("/api/v1/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
  },
  uploadAssets(projectId: string, files: File[]) {
    const body = new FormData();
    files.forEach((file) => body.append("files", file));
    return request<ProjectAsset[]>(`/api/v1/projects/${projectId}/assets`, {
      method: "POST",
      body,
    });
  },
  uploadConfirmedTwoD(projectId: string, files: File[]) {
    const body = new FormData();
    files.forEach((file) => body.append("files", file));
    return request<ProjectAsset[]>(`/api/v1/projects/${projectId}/assets/confirmed-2d`, {
      method: "POST",
      body,
    });
  },
  getProject(projectId: string) {
    return request<Project>(`/api/v1/projects/${projectId}`);
  },
  assetContentUrl(projectId: string, assetId: string) {
    return `${API_BASE}/api/v1/projects/${projectId}/assets/${assetId}/content`;
  },
  updateAssetRole(projectId: string, assetId: string, role: "original" | "confirmed_2d") {
    return request<ProjectAsset>(`/api/v1/projects/${projectId}/assets/${assetId}/role`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    });
  },
  generateTwoDCandidates(projectId: string, sourceAssetId: string, settings: Record<string, unknown> = {}) {
    return request<TwoDCandidate[]>(`/api/v1/projects/${projectId}/2d-candidates`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_asset_id: sourceAssetId, ...settings }),
    });
  },
  generateModelTwoDCandidates(projectId: string, sourceAssetId: string, settings: Record<string, unknown> = {}) {
    return request<TwoDCandidate[]>(`/api/v1/projects/${projectId}/2d-candidates/model`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_asset_id: sourceAssetId, ...settings }),
    });
  },
  listTwoDCandidates(projectId: string, sourceAssetId: string) {
    return request<TwoDCandidate[]>(
      `/api/v1/projects/${projectId}/2d-candidates/${sourceAssetId}`,
    );
  },
  confirmTwoDCandidate(projectId: string, candidateAssetId: string) {
    return request<ProjectAsset>(`/api/v1/projects/${projectId}/2d-candidates/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ candidate_asset_id: candidateAssetId }),
    });
  },
  backupUrl(projectId: string) {
    return `${API_BASE}/api/v1/projects/${projectId}/backup`;
  },
  importBackup(file: File) {
    const body = new FormData();
    body.append("file", file);
    return request<{ project: Project; source_project_id: string }>(
      "/api/v1/project-backups/import",
      { method: "POST", body },
    );
  },
  generatePattern(projectId: string, sourceAssetId: string, boardLayout: string, colorMode: string, generationMode: "local" | "model_direct") {
    return request<GeneratedPattern>(`/api/v1/projects/${projectId}/patterns/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_asset_id: sourceAssetId,
        board_layout: boardLayout,
        color_mode: colorMode,
        generation_mode: generationMode,
      }),
    });
  },
  getLatestPattern(projectId: string, sourceAssetId?: string) {
    return request<GeneratedPattern>(`/api/v1/projects/${projectId}/patterns:latest${sourceAssetId ? `?source_asset_id=${encodeURIComponent(sourceAssetId)}` : ""}`);
  },
  archiveProject(projectId: string, archived: boolean) {
    return request<Project>(`/api/v1/projects/${projectId}/archive`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ archived }) });
  },
  archiveAsset(projectId: string, assetId: string, archived: boolean) {
    return request<Project>(`/api/v1/projects/${projectId}/assets/${assetId}/archive`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ archived }) });
  },
  updatePattern(projectId: string, patternId: string, pattern: GeneratedPattern["pattern"] & Record<string, unknown>, expectedRevision: number) {
    return request<GeneratedPattern>(`/api/v1/projects/${projectId}/patterns/${patternId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pattern, expected_revision: expectedRevision }),
    });
  },
  listPatternVersions(projectId: string, patternId: string) {
    return request<{ items: PatternVersion[]; total: number }>(
      `/api/v1/projects/${projectId}/patterns/${patternId}/versions`,
    );
  },
  createPatternVersion(projectId: string, patternId: string, name: string, note: string, expectedRevision: number) {
    return request<PatternVersion>(`/api/v1/projects/${projectId}/patterns/${patternId}/versions`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ name, note, expected_revision: expectedRevision }),
    });
  },
  listStageVersions(projectId: string, stage: "twod" | "board" | "pattern" | "editor") {
    return request<{ items: StageVersion[]; total: number }>(`/api/v1/projects/${projectId}/stage-versions/${stage}`);
  },
  createStageVersion(projectId: string, stage: "twod" | "board" | "pattern" | "editor", name: string, snapshot: Record<string, unknown>) {
    return request<StageVersion>(`/api/v1/projects/${projectId}/stage-versions/${stage}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, snapshot }) });
  },
  getStageVersion(projectId: string, stage: "twod" | "board" | "pattern" | "editor", versionId: string) {
    return request<StageVersion>(`/api/v1/projects/${projectId}/stage-versions/${stage}/${versionId}`);
  },
  getPatternVersion(projectId: string, patternId: string, versionId: string) {
    return request<PatternVersion>(
      `/api/v1/projects/${projectId}/patterns/${patternId}/versions/${versionId}`,
    );
  },
  restorePatternVersion(projectId: string, patternId: string, versionId: string, expectedRevision: number) {
    return request<GeneratedPattern>(
      `/api/v1/projects/${projectId}/patterns/${patternId}/versions/${versionId}/restore`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ expected_revision: expectedRevision }),
      },
    );
  },
  inspectPattern(projectId: string, patternId: string) {
    return request<{ inspected_revision: number; summary: { total: number; warning: number; info: number; blocking: number }; issues: PatternIssue[] }>(
      `/api/v1/projects/${projectId}/patterns/${patternId}/inspect`,
      { method: "POST" },
    );
  },
  createPatternExport(projectId: string, patternId: string, expectedRevision: number, watermark?: {
    enabled: boolean;
    text: string;
    color: string;
    font: string;
    size: number;
    opacity: number;
    rotation: number;
    x: number;
    y: number;
  }, includeMirroredPattern = false) {
    return request<PatternExport>(
      `/api/v1/projects/${projectId}/patterns/${patternId}/exports`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_revision: expectedRevision, watermark, include_mirrored_pattern: includeMirroredPattern }),
      },
    );
  },
  getBrandColors(brandCode: string) {
    return request<{ brand: string; paletteVersion: string; colors: BeadColor[] }>(`/api/v1/bead-brands/${brandCode}/colors`);
  },
  exportDownloadUrl(projectId: string, patternId: string, revision: number) {
    return `${API_BASE}/api/v1/projects/${projectId}/patterns/${patternId}/exports/${revision}/download`;
  },
  listBatches(projectId: string) {
    return request<{ items: BatchJob[]; total: number }>(`/api/v1/projects/${projectId}/batches`);
  },
  createBatch(projectId: string, sourceAssetIds: string[], boardLayout: string, colorMode: string) {
    return request<BatchJob>(`/api/v1/projects/${projectId}/batches`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_asset_ids: sourceAssetIds, board_layout: boardLayout, color_mode: colorMode }),
    });
  },
  retryBatch(projectId: string, batchId: string) {
    return request<BatchJob>(`/api/v1/projects/${projectId}/batches/${batchId}/retry`, { method: "POST" });
  },
  confirmBatch(projectId: string, batchId: string, itemIds: string[]) {
    return request<BatchJob>(`/api/v1/projects/${projectId}/batches/${batchId}/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_ids: itemIds }),
    });
  },
  createBatchExport(projectId: string, batchId: string) {
    return request<{ filename: string; item_count: number; size_bytes: number; download_url: string }>(
      `/api/v1/projects/${projectId}/batches/${batchId}/export`, { method: "POST" },
    );
  },
  batchExportDownloadUrl(projectId: string, batchId: string) {
    return `${API_BASE}/api/v1/projects/${projectId}/batches/${batchId}/export/download`;
  },
};
