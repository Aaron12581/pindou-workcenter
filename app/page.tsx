"use client";

// @ts-nocheck
/* eslint-disable react-hooks/set-state-in-effect */

import {
  ArrowClockwise, ArrowCounterClockwise, ArrowRight, CaretDown, CaretLeft,
  CaretRight, CaretUp, Check, Circle, Copy, DotsNine, Eraser, Export, Eye,
  Eyedropper, FileText, Folder, Gear, Layout, MagnifyingGlass, PaintBucket,
  PencilSimple, Play, Plus, Selection, ShareNetwork, SquaresFour,
  WarningCircle, Minus, UploadSimple, ImageSquare, Crop, MagicWand,
  CheckCircle, Stack, ArrowsOutLineHorizontal, BoundingBox, GridFour, Ruler, ShieldCheck,
  X, ClockCounterClockwise, ListChecks, DownloadSimple, Hand,
  SidebarSimple, Archive,
} from "@phosphor-icons/react";
import { useEffect, useImperativeHandle, useRef, useState } from "react";
import { ApiError, api } from "../lib/api-client";

const topTabs = ["素材", "2D", "图板", "图纸", "编辑", "导出"];
const projectNav = [
  ["图纸", FileText, "3"], ["2D 预览", Eye], ["图板规划", Layout],
  ["配色方案", ShareNetwork], ["导出设置", Export],
];
const folders = ["全部", "已归档"];
const tools = [
  ["画笔", PencilSimple], ["橡皮", Eraser], ["吸色", Eyedropper],
  ["框选", Selection], ["批量擦除", Eraser], ["撤销", ArrowCounterClockwise], ["重做", ArrowClockwise],
];
const extras = [["填充", PaintBucket], ["复制", Copy]];
const swatches = [
  ["H2", "#fbfbfb"], ["H4", "#ffe5ad"], ["C6", "#ffd83f"], ["C10", "#ff9f1c"],
  ["E15", "#f7a6b3"], ["F11", "#ef5f55"], ["M2", "#6aa735"], ["M4", "#78bc49"],
  ["M7", "#197844"], ["H3", "#a35f26"], ["H7", "#222"], ["H1", "#eee"],
];
function derivePattern(pattern, cellMap) {
  const cells = [...cellMap.values()].sort((a, b) => a.y - b.y || a.x - b.x);
  const counts = new Map();
  for (const cell of cells) counts.set(cell.colorCode, (counts.get(cell.colorCode) || 0) + 1);
  const known = new Map((pattern.palette || []).map((item) => [item.code, item]));
  const palette = [...counts.entries()].map(([code, count]) => ({
    ...(known.get(code) || { brand: "MARD", code, value: cells.find((cell) => cell.colorCode === code)?.colorValue }),
    count,
  }));
  return { ...pattern, cells, palette, statistics: { ...pattern.statistics, totalBeads: cells.length, colorCount: palette.length } };
}

const DEFAULT_WATERMARK_TEMPLATES = [
  { enabled: true, text: "@我的拼豆店", color: "#526c7e", font: "sans", size: 72, opacity: 55, rotation: 0, x: 82, y: 94 },
  { enabled: true, text: "仅供个人使用", color: "#805ad5", font: "elegant", size: 96, opacity: 38, rotation: 330, x: 50, y: 50 },
  { enabled: true, text: "原创图纸", color: "#dd7777", font: "rounded", size: 88, opacity: 45, rotation: 20, x: 72, y: 20 },
];

// Board planning is project-and-formal-2D specific.  Keeping it separate from
// a generated pattern means a user can return to the pattern stage and choose
// any custom board combination they have already applied for this artwork.
const BOARD_PLAN_STORAGE_KEY = "perler-board-plans-v1";

function boardPlanStorageKey(projectId, sourceAssetId) {
  return projectId && sourceAssetId ? `${projectId}:${sourceAssetId}` : "";
}

function isCustomBoardLayout(layout) {
  return /^custom_\d+x\d+$/.test(layout || "");
}

function customBoardLabel(layout) {
  const match = /^custom_(\d+)x(\d+)$/.exec(layout || "");
  return match
    ? `自定义 ${match[1]}×${match[2]} 板 · ${Number(match[1]) * 52}×${Number(match[2]) * 52}`
    : layout;
}

/* eslint-disable react-hooks/exhaustive-deps */
function PatternBoard({ zoom, setZoom, result, tool, selectedColor, setSelectedColor, onChange, editorApiRef, viewOptions, inspectionIssue, onBatchErase }) {
  const pattern = result.pattern;
  const { width, height } = pattern;
  const boardWidth = pattern.boardLayout?.boardWidth || 29;
  const boardHeight = pattern.boardLayout?.boardHeight || 29;
  const boardIdAt = (x, y) => `${String.fromCharCode(65 + Math.floor(y / boardHeight))}${Math.floor(x / boardWidth) + 1}`;
  const [cellMap, setCellMap] = useState(() => new Map(pattern.cells.map((cell) => [`${cell.x}:${cell.y}`, cell])));
  const [selection, setSelection] = useState(null);
  const [selectionDraft, setSelectionDraft] = useState(null);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const undoRef = useRef([]);
  const redoRef = useRef([]);
  const dragging = useRef(false);
  const dragStart = useRef(null);
  const panStart = useRef(null);
  const selectionDraftRef = useRef(null);
  const gridRef = useRef(null);
  const mapRef = useRef(cellMap);
  useEffect(() => { mapRef.current = cellMap; }, [cellMap]);
  const commit = (next, record = true) => {
    if (record) { undoRef.current.push(mapRef.current); if (undoRef.current.length > 80) undoRef.current.shift(); redoRef.current = []; }
    mapRef.current = next;
    setCellMap(next);
    onChange(derivePattern(pattern, next));
  };
  const normalizedSelection = (value = selectionDraft || selection) => value ? {
    x1: Math.min(value.x1, value.x2), y1: Math.min(value.y1, value.y2),
    x2: Math.max(value.x1, value.x2), y2: Math.max(value.y1, value.y2),
  } : null;
  const moveSelection = (dx, dy, mode = "move") => {
    const box = normalizedSelection(selection);
    if (!box || (!dx && !dy)) return false;
    const selected = [...mapRef.current.values()].filter((cell) => cell.x >= box.x1 && cell.x <= box.x2 && cell.y >= box.y1 && cell.y <= box.y2);
    if (!selected.length) return false;
    if (selected.some((cell) => cell.x + dx < 0 || cell.y + dy < 0 || cell.x + dx >= width || cell.y + dy >= height)) return "out-of-bounds";
    const next = new Map(mapRef.current);
    if (mode === "move") selected.forEach((cell) => next.delete(`${cell.x}:${cell.y}`));
    selected.forEach((cell) => {
      const x = cell.x + dx, y = cell.y + dy;
      next.set(`${x}:${y}`, { ...cell, x, y, boardId: boardIdAt(x, y) });
    });
    commit(next);
    setSelection({ x1: box.x1 + dx, y1: box.y1 + dy, x2: box.x2 + dx, y2: box.y2 + dy });
    return true;
  };
  const eraseSelection = (value = selectionDraftRef.current || selection) => {
    const box = normalizedSelection(value);
    if (!box) return 0;
    const next = new Map(mapRef.current);
    let erased = 0;
    for (let y = box.y1; y <= box.y2; y += 1) {
      for (let x = box.x1; x <= box.x2; x += 1) {
        if (next.delete(`${x}:${y}`)) erased += 1;
      }
    }
    setSelection(box);
    if (erased) commit(next);
    return erased;
  };
  const applyAt = (x, y, activeTool = tool) => {
    const currentMap = mapRef.current;
    const key = `${x}:${y}`, existing = currentMap.get(key);
    if (activeTool === "吸色") {
      if (existing) setSelectedColor({ code: existing.colorCode, value: existing.colorValue });
      return;
    }
    if (activeTool === "填充") {
      const target = existing?.colorCode || null;
      if ((selectedColor?.code || null) === target) return;
      const next = new Map(currentMap), queue = [[x, y]], visited = new Set();
      while (queue.length) {
        const [cx, cy] = queue.pop(), currentKey = `${cx}:${cy}`;
        if (visited.has(currentKey) || cx < 0 || cy < 0 || cx >= width || cy >= height) continue;
        visited.add(currentKey);
        if ((currentMap.get(currentKey)?.colorCode || null) !== target) continue;
        next.set(currentKey, { x: cx, y: cy, occupied: true, brand: "MARD", colorCode: selectedColor.code, colorValue: selectedColor.value, boardId: boardIdAt(cx, cy), matchDistanceRgb: 0 });
        queue.push([cx - 1, cy], [cx + 1, cy], [cx, cy - 1], [cx, cy + 1]);
      }
      commit(next); return;
    }
    const next = new Map(currentMap);
    if (activeTool === "橡皮") next.delete(key);
    else if (activeTool === "画笔" && selectedColor) next.set(key, { x, y, occupied: true, brand: "MARD", colorCode: selectedColor.code, colorValue: selectedColor.value, boardId: boardIdAt(x, y), matchDistanceRgb: 0 });
    else return;
    if (JSON.stringify(existing) !== JSON.stringify(next.get(key))) commit(next);
  };
  useImperativeHandle(editorApiRef, () => ({
    undo: () => { const previous = undoRef.current.pop(); if (!previous) return false; redoRef.current.push(mapRef.current); commit(new Map(previous), false); return true; },
    redo: () => { const next = redoRef.current.pop(); if (!next) return false; undoRef.current.push(mapRef.current); commit(new Map(next), false); return true; },
    copySelection: () => moveSelection(1, 1, "copy"),
    eraseSelection: () => eraseSelection(),
  }), [selection, selectionDraft]);
  useEffect(() => {
    const onKey = (event) => {
      if (!selection || !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
      event.preventDefault();
      const delta = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] }[event.key];
      moveSelection(delta[0], delta[1], event.altKey ? "copy" : "move");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selection]);
  const cellSize = Math.max(8, Math.min(13, 696 / Math.max(width, height)));
  const stageWidth = width * cellSize + 22, stageHeight = height * cellSize + 22;
  const box = normalizedSelection();
  const issueCells = new Set((inspectionIssue?.coordinates || []).map((item) => `${item.x}:${item.y}`));
  const gridPoint = (event) => {
    const rect = gridRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const x = Math.max(0, Math.min(width - 1, Math.floor((event.clientX - rect.left) / (rect.width / width))));
    const y = Math.max(0, Math.min(height - 1, Math.floor((event.clientY - rect.top) / (rect.height / height))));
    return { x, y };
  };
  const updateDrag = (point) => {
    if (!point || !dragging.current) return;
    if ((tool === "框选" || tool === "批量擦除") && dragStart.current) {
      const draft = { x1: dragStart.current.x, y1: dragStart.current.y, x2: point.x, y2: point.y };
      selectionDraftRef.current = draft;
      setSelectionDraft(draft);
    } else if (tool === "画笔" || tool === "橡皮") applyAt(point.x, point.y);
  };
  const finishDrag = (point) => {
    updateDrag(point);
    if (!dragging.current) return;
    dragging.current = false;
    if (tool === "框选" || tool === "批量擦除") {
      const draft = normalizedSelection(selectionDraftRef.current);
      if (tool === "批量擦除") {
        const erased = eraseSelection(draft);
        onBatchErase?.(erased, draft);
      } else setSelection(draft);
      selectionDraftRef.current = null;
      setSelectionDraft(null);
    }
    dragStart.current = null;
  };
  const cells = Array.from({ length: height }, (_, row) => Array.from({ length: width }, (_, col) => {
    const cell = cellMap.get(`${col}:${row}`), color = cell?.colorValue;
    const selected = box && col >= box.x1 && col <= box.x2 && row >= box.y1 && row <= box.y2;
    const classes = ["pattern-cell", cell ? "filled" : "empty", selected ? "cell-selected" : "", issueCells.has(`${col}:${row}`) ? "inspection-highlight" : "", viewOptions.markings && col > 0 && col % 5 === 0 ? "mark-v" : "", viewOptions.markings && row > 0 && row % 5 === 0 ? "mark-h" : "", viewOptions.markings && col > 0 && col % 10 === 0 ? "mark-v-major" : "", viewOptions.markings && row > 0 && row % 10 === 0 ? "mark-h-major" : "", viewOptions.seams && pattern.boardLayout.seamsX?.includes(col) ? "board-seam-v" : "", viewOptions.seams && pattern.boardLayout.seamsY?.includes(row) ? "board-seam-h" : ""].filter(Boolean).join(" ");
    return <button className={classes} key={`${row}-${col}`} data-grid-x={col} data-grid-y={row} style={color ? { "--bead": color, "--ink": "#16212a" } : undefined}
      onContextMenu={(event) => { event.preventDefault(); applyAt(col, row, "吸色"); }}>
      {cell && <><i />{viewOptions.codes && <span>{cell.colorCode}</span>}</>}
    </button>;
  })).flat();
  return <div className="pattern-shell">
    <div className="pattern-meta"><div><strong>真实 Pattern JSON</strong><span>{width} × {height} / {pattern.statistics.colorCount} 色 / 共 {pattern.statistics.totalBeads.toLocaleString()} 颗</span></div><div className="zoom-control"><button onClick={() => setZoom(Math.max(50, zoom - 25))} aria-label="缩小图纸"><Minus size={14} /></button><span>{zoom}%</span><button onClick={() => setZoom(Math.min(200, zoom + 25))} aria-label="放大图纸"><Plus size={14} /></button></div></div>
    <div className={`pattern-scroll ${tool === "平移" ? "is-panning" : ""}`} onPointerDown={(event) => { if (tool !== "平移") return; event.currentTarget.setPointerCapture(event.pointerId); panStart.current = { clientX: event.clientX, clientY: event.clientY, x: pan.x, y: pan.y }; }} onPointerMove={(event) => { if (!panStart.current) return; setPan({ x: panStart.current.x + event.clientX - panStart.current.clientX, y: panStart.current.y + event.clientY - panStart.current.clientY }); }} onPointerUp={() => { panStart.current = null; }}>
      <div className="pattern-stage" style={{ "--zoom": zoom / 100, width: stageWidth, height: stageHeight, translate: `${pan.x}px ${pan.y}px` }}>
      {viewOptions.coordinates && <><div className="axis axis-top" style={{ width: width * cellSize, gridTemplateColumns: `repeat(${width},1fr)` }}>{Array.from({ length: width }, (_, n) => <span key={n}>{n === 0 || (n + 1) % 5 === 0 || n === width - 1 ? n + 1 : ""}</span>)}</div>
      <div className="axis axis-left" style={{ height: height * cellSize, gridTemplateRows: `repeat(${height},1fr)` }}>{Array.from({ length: height }, (_, n) => <span key={n}>{n === 0 || (n + 1) % 5 === 0 || n === height - 1 ? n + 1 : ""}</span>)}</div></>}
      <div ref={gridRef} className="pattern-grid" style={{ width: width * cellSize, height: height * cellSize, gridTemplateColumns: `repeat(${width},1fr)`, gridTemplateRows: `repeat(${height},1fr)` }}
        onPointerDown={(event) => { if (event.button !== 0) return; const point = gridPoint(event); if (!point) return; event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId); dragging.current = true; dragStart.current = point; if (tool === "框选" || tool === "批量擦除") { const draft = { x1: point.x, y1: point.y, x2: point.x, y2: point.y }; selectionDraftRef.current = draft; setSelectionDraft(draft); } else applyAt(point.x, point.y); }}
        onPointerMove={(event) => updateDrag(gridPoint(event))}
        onPointerUp={(event) => finishDrag(gridPoint(event))}
        onPointerCancel={() => finishDrag(null)}>{cells}</div>
    </div></div>
    <div className="pattern-legend">{pattern.palette.map((item) => <span key={item.code}><i style={{ background: item.value }} />{item.code} · {item.count}</span>)}</div>
  </div>;
}
/* eslint-enable react-hooks/exhaustive-deps */

export default function Home() {
  const [tab, setTab] = useState("编辑");
  const [nav, setNav] = useState("图纸");
  const [tool, setTool] = useState("画笔");
  const [extra, setExtra] = useState(false);
  const [suggestion, setSuggestion] = useState(0);
  const [versions, setVersions] = useState([]);
  const [selectedVersion, setSelectedVersion] = useState(null);
  const [versionPreview, setVersionPreview] = useState(null);
  const [inspection, setInspection] = useState(null);
  const [scheme, setScheme] = useState(false);
  const [palette, setPalette] = useState(true);
  const [board, setBoard] = useState(true);
  const [history, setHistory] = useState(true);
  const [toast, setToast] = useState("");
  const [compare, setCompare] = useState(false);
  const [approved, setApproved] = useState(false);
  const [zoom, setZoom] = useState(100);
  const [surface, setSurface] = useState("workbench");
  const [auxPanel, setAuxPanel] = useState("");
  const [projectFilter, setProjectFilter] = useState("全部");
  const [projectSearch, setProjectSearch] = useState("");
  const [projects, setProjects] = useState([]);
  const [archivedProjects, setArchivedProjects] = useState([]);
  const [activeProject, setActiveProject] = useState(null);
  const [activeSourceAssetId, setActiveSourceAssetId] = useState(null);
  const [activePattern, setActivePattern] = useState(null);
  const [editedPattern, setEditedPattern] = useState(null);
  const [selectedColor, setSelectedColor] = useState(null);
  const [officialColors, setOfficialColors] = useState([]);
  const [showOfficialColors, setShowOfficialColors] = useState(false);
  const [saveState, setSaveState] = useState("等待图纸");
  const [viewOptions, setViewOptions] = useState({ codes: true, coordinates: true, markings: true, seams: true });
  const editorApi = useRef({});
  const latestEditRef = useRef(null);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [apiError, setApiError] = useState("");
  const [boardLayout, setBoardLayout] = useState("single");
  const [boardPlans, setBoardPlans] = useState({});
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true);
  const projectOriginal = activeProject?.assets?.find((asset) => asset.id === activeSourceAssetId) || activeProject?.assets?.find((asset) => asset.role === "original" && !asset.archived);
  const projectTwoD = activeProject?.assets?.find((asset) => asset.id === activeSourceAssetId && asset.role === "confirmed_2d") || activeProject?.assets?.find((asset) => asset.role === "confirmed_2d" && !asset.archived);

  const notify = (message) => {
    setToast(message);
    window.setTimeout(() => setToast(""), 2200);
  };
  const nextSuggestion = (delta) => {
    const total = inspection?.issues?.length || 0;
    const next = Math.min(Math.max(0, total - 1), Math.max(0, suggestion + delta));
    setSuggestion(next);
    if (next !== suggestion) notify(`已切换至问题 ${next + 1}`);
  };
  const refreshPatternTools = async (projectId, patternId) => {
    const [versionResult, inspectionResult] = await Promise.all([
      api.listPatternVersions(projectId, patternId),
      api.inspectPattern(projectId, patternId),
    ]);
    setVersions(versionResult.items);
    setInspection(inspectionResult);
    setSuggestion(0);
  };
  useEffect(() => {
    api.getBrandColors("MARD").then((response) => setOfficialColors(response.colors || [])).catch(() => setOfficialColors([]));
  }, []);
  const goTo = (name) => {
    const map = { "2D 预览": "2D", "图板规划": "图板", "配色方案": "图纸", "导出设置": "导出", "图纸": "编辑" };
    setNav(name);
    setTab(map[name] || name);
    notify(`已切换到${name}`);
  };
  const refreshProjects = async () => {
    setProjectsLoading(true);
    setApiError("");
    try {
      const [result, archived] = await Promise.all([api.listProjects(false), api.listProjects(true)]);
      setProjects(result.items);
      setArchivedProjects(archived.items);
    } catch {
      setApiError("无法连接本机数据服务，请确认本地应用已经启动。");
    } finally {
      setProjectsLoading(false);
    }
  };
  useEffect(() => {
    const saved = window.localStorage.getItem("perler.sidebar.collapsed");
    if (saved !== null) setSidebarCollapsed(saved === "true");
    try {
      setBoardPlans(JSON.parse(window.localStorage.getItem(BOARD_PLAN_STORAGE_KEY) || "{}"));
    } catch {
      window.localStorage.removeItem(BOARD_PLAN_STORAGE_KEY);
    }
  }, []);
  useEffect(() => {
    window.localStorage.setItem("perler.sidebar.collapsed", String(sidebarCollapsed));
  }, [sidebarCollapsed]);
  const activeBoardPlanKey = boardPlanStorageKey(activeProject?.id, activeSourceAssetId);
  const activeBoardPlan = activeBoardPlanKey ? boardPlans[activeBoardPlanKey] : null;
  const availableCustomLayouts = Array.from(new Set([
    ...(activeBoardPlan?.customLayouts || []),
    ...(isCustomBoardLayout(activeBoardPlan?.layout) ? [activeBoardPlan.layout] : []),
  ])).filter(isCustomBoardLayout);
  const saveBoardLayout = (layout) => {
    setBoardLayout(layout);
    if (!activeBoardPlanKey) return;
    setBoardPlans((previous) => {
      const saved = previous[activeBoardPlanKey] || { customLayouts: [] };
      const customLayouts = Array.from(new Set([
        ...(saved.customLayouts || []),
        ...(isCustomBoardLayout(layout) ? [layout] : []),
      ])).filter(isCustomBoardLayout);
      const next = { ...previous, [activeBoardPlanKey]: { layout, customLayouts } };
      window.localStorage.setItem(BOARD_PLAN_STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  };
  useEffect(() => {
    if (!activeBoardPlanKey) return;
    setBoardLayout(activeBoardPlan?.layout || "single");
  }, [activeBoardPlanKey, activeBoardPlan?.layout]);
  useEffect(() => {
    let active = true;
    Promise.all([api.listProjects(false), api.listProjects(true)])
      .then(([result, archived]) => { if (active) { setProjects(result.items); setArchivedProjects(archived.items); } })
      .catch(() => { if (active) setApiError("无法连接本机数据服务，请确认本地应用已经启动。"); })
      .finally(() => { if (active) setProjectsLoading(false); });
    return () => { active = false; };
  }, []);
  const openProject = async (project) => {
    try {
      const loaded = await api.getProject(project.id);
      setActiveProject(loaded);
      try {
        const latest = await api.getLatestPattern(loaded.id);
        setActiveSourceAssetId(latest.source_asset_id);
        setActivePattern(latest); setEditedPattern(latest.pattern); latestEditRef.current = latest.pattern;
        setSelectedVersion(null); setVersionPreview(null);
        await refreshPatternTools(loaded.id, latest.id);
        setSelectedColor(latest.pattern.palette?.[0] ? { code: latest.pattern.palette[0].code, value: latest.pattern.palette[0].value } : null);
      } catch { setActivePattern(null); setEditedPattern(null); setVersions([]); setInspection(null); setActiveSourceAssetId(loaded.assets.find((asset) => asset.role === "confirmed_2d" && !asset.archived)?.id || loaded.assets.find((asset) => asset.role === "original" && !asset.archived)?.id || null); }
      setSurface("workbench");
      setTab(loaded.assets.length ? "素材" : "素材");
      setNav("图纸");
      notify(`已打开项目：${loaded.name}`);
    } catch {
      notify("项目打开失败，请检查本机数据服务");
    }
  };
  useEffect(() => {
    if (!activeProject || !activePattern || !editedPattern) return;
    if (editedPattern === activePattern.pattern) return;
    const timer = window.setTimeout(async () => {
      setSaveState("正在自动保存…");
      try {
        const saved = await api.updatePattern(activeProject.id, activePattern.id, editedPattern, activePattern.pattern.revision ?? 0);
        setActivePattern(saved);
        if (latestEditRef.current === editedPattern) {
          latestEditRef.current = saved.pattern;
          setEditedPattern(saved.pattern);
          setSaveState("已自动保存");
        }
      } catch (cause) {
        setSaveState(cause instanceof Error && cause.message === "PATTERN_VERSION_CONFLICT" ? "保存冲突，请重新打开项目" : "自动保存失败");
      }
    }, 900);
    return () => window.clearTimeout(timer);
  }, [editedPattern, activeProject, activePattern]);
  const createProject = async (name) => {
    const created = await api.createProject(name);
    setActiveProject(created);
    await refreshProjects();
    setAuxPanel("");
    setSurface("workbench");
    setTab("素材");
    setNav("图纸");
    notify("项目已创建，请添加素材");
  };
  const restoreBackup = async (file) => {
    const result = await api.importBackup(file);
    setActiveProject(result.project);
    await refreshProjects();
    setAuxPanel("");
    setSurface("workbench");
    setTab("素材");
    notify(`已恢复项目：${result.project.name}`);
  };
  const createVersion = async () => {
    if (tab !== "编辑") return notify("当前阶段请使用标题栏中的独立版本入口；编辑版本不会混入图板或图纸。 ");
    if (!activeProject || !activePattern) return notify("请先打开真实图纸");
    if (saveState === "有未保存修改" || saveState.includes("正在")) return notify("请等待自动保存完成");
    try {
      const nextNo = (versions[0]?.version_no || 0) + 1;
      await api.createPatternVersion(
        activeProject.id, activePattern.id, `V${nextNo}`, "手动保存的关键版本",
        activePattern.pattern.revision ?? 0,
      );
      const result = await api.listPatternVersions(activeProject.id, activePattern.id);
      setVersions(result.items);
      notify(`已创建版本 V${nextNo}`);
    } catch (cause) {
      notify(cause instanceof Error && cause.message === "PATTERN_VERSION_CONFLICT" ? "版本已变化，请重新打开项目" : "创建版本失败");
    }
  };
  const openEditorHistory = () => {
    if (tab !== "编辑") return notify("当前阶段请使用本页的独立版本记录；不会跳转到编辑版本。 ");
    setHistory(true);
    notify(`已打开 ${versions.length} 个编辑关键版本`);
  };
  const previewVersion = async (item) => {
    if (!activeProject || !activePattern) return;
    try {
      const detail = await api.getPatternVersion(activeProject.id, activePattern.id, item.id);
      setSelectedVersion(item.id);
      setVersionPreview(detail.pattern);
      notify(`正在对比 V${item.version_no} 与当前工作副本`);
    } catch { notify("读取版本失败"); }
  };
  const restoreVersion = async () => {
    if (!activeProject || !activePattern || !selectedVersion) return;
    try {
      const restored = await api.restorePatternVersion(
        activeProject.id, activePattern.id, selectedVersion, activePattern.pattern.revision ?? 0,
      );
      setActivePattern(restored); setEditedPattern(restored.pattern); latestEditRef.current = restored.pattern;
      setSelectedVersion(null); setVersionPreview(null); setSaveState("已恢复并保存");
      await refreshPatternTools(activeProject.id, activePattern.id);
      notify("历史版本已恢复为新的工作副本");
    } catch { notify("恢复失败，图纸可能已在其他页面更新"); }
  };
  const runInspection = async () => {
    if (!activeProject || !activePattern) return notify("请先生成真实图纸");
    try {
      const result = await api.inspectPattern(activeProject.id, activePattern.id);
      setInspection(result); setSuggestion(0);
      notify(result.summary.total ? `检查完成：发现 ${result.summary.total} 项待确认` : "检查完成：未发现问题");
    } catch { notify("图纸检查失败"); }
  };
  const currentIssue = inspection?.issues?.[suggestion] || null;

  return (
    <main className={`app-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <aside className="sidebar">
        <div className="brand"><img src="/assets/brand-lockup.png" alt="拼豆工作台" /><button className="sidebar-toggle" aria-label={sidebarCollapsed ? "展开左侧栏" : "收起左侧栏"} onClick={() => setSidebarCollapsed(!sidebarCollapsed)}><SidebarSimple size={19}/></button></div>
        <button className="new-project" onClick={() => setAuxPanel("new")}><Plus size={20} weight="bold" />新建项目</button>
        <div className="side-head"><button className="side-head-link" onClick={() => setSurface("projects")}>我的项目</button><button aria-label="搜索项目" onClick={() => setSurface("projects")}><MagnifyingGlass size={18} /></button></div>
        <div className="project-card">
          <button className="project-title" onClick={() => setSurface("projects")}>
            <img src={activeProject && projectOriginal ? api.assetContentUrl(activeProject.id, projectOriginal.id) : "/assets/project-thumb.png"} alt={activeProject?.name || "当前项目"} />
            <div><strong>{activeProject?.name || "未打开项目"}</strong><span><i />{activeProject ? "进行中" : "请选择项目"}</span></div>
          </button>
          <nav aria-label="项目步骤">
            {projectNav.map(([label, Icon, badge]) => (
              <button key={label} className={`project-nav ${nav === label ? "active" : ""}`} onClick={() => goTo(label)}>
                <Icon size={18} weight={nav === label ? "fill" : "regular"} /><span>{label}</span>{badge && <b>{badge}</b>}
              </button>
            ))}
          </nav>
        </div>
        <div className="side-head library"><span>项目库</span><CaretUp size={15} /></div>
        <div className="folder-list">{projects.slice(0, 6).map((item) => <button key={item.id} onClick={() => openProject(item)}><Folder size={18} />{item.name}</button>)}<button onClick={() => { setProjectFilter("已归档"); setSurface("projects"); }}><Archive size={18} />已归档 {archivedProjects.length ? `(${archivedProjects.length})` : ""}</button></div>
        <div className="account">
          <img src="/assets/avatar.png" alt="" />
          <div><strong>小豆手作</strong><span>基础版 <CaretDown size={11} /></span></div>
          <button aria-label="设置" onClick={() => setAuxPanel("settings")}><Gear size={20} /></button>
        </div>
      </aside>

      <section className="workspace">
        {surface === "projects" ? <ProjectCenter
          filter={projectFilter}
          setFilter={setProjectFilter}
          search={projectSearch}
          setSearch={setProjectSearch}
          projects={projects}
          archivedProjects={archivedProjects}
          loading={projectsLoading}
          error={apiError}
          onRetry={refreshProjects}
          onOpen={openProject}
          onBackup={(project) => { window.location.href = api.backupUrl(project.id); notify("项目备份下载已开始"); }}
          onNew={() => setAuxPanel("new")}
          onPanel={setAuxPanel}
          onArchive={async (item, archived) => { const updated = await api.archiveProject(item.id, archived); await refreshProjects(); if (activeProject?.id === item.id && archived) { setActiveProject(null); setActivePattern(null); setEditedPattern(null); } notify(archived ? `已归档项目：${updated.name}` : `已恢复项目：${updated.name}`); }}
        /> : <>
        <header className="topbar">
          {sidebarCollapsed && <button className="top-sidebar-toggle" aria-label="展开左侧栏" onClick={() => setSidebarCollapsed(false)}><SidebarSimple size={20}/></button>}
          <nav className="steps" aria-label="项目工作流">
            {topTabs.map((name, index) => (
              <div className="step-wrap" key={name}>
                <button className={`step ${tab === name ? "active" : ""}`} onClick={() => { setTab(name); notify(`已切换到${name}阶段`); }}>{name}</button>
                {index < topTabs.length - 1 && <span>/</span>}
              </div>
            ))}
          </nav>
          <div className="top-actions">
            {tab === "素材" ? <>
              <button className="outline" onClick={() => notify("已打开批量素材选择器")}><UploadSimple size={16} />继续添加</button>
              <button className="primary top-primary" onClick={() => { setTab("2D"); notify("素材已确认，进入 2D 生成"); }}>确认素材并进入 2D <ArrowRight size={19} weight="bold" /></button>
            </> : tab === "2D" ? <>
              <button className="outline" onClick={() => notify("已切换原图对照显示")}><Eye size={16} />原图对照</button>
              <button className="outline" onClick={() => notify("已根据当前参数重新生成 3 个候选")}><ArrowClockwise size={16} />重新生成候选</button>
            </> : <>
            <button className="outline" onClick={() => setCompare(true)}><Play size={15} weight="fill" />查看原图与2D</button>
            <button className="outline" onClick={createVersion}><ClockCounterClockwise size={16} />保存关键版本</button>
            <button className="outline" disabled={tab === "编辑" && !versions.length} onClick={openEditorHistory}><Archive size={16} />编辑关键版本 {versions.length ? `(${versions.length})` : ""}</button>
            <button className="primary top-primary" onClick={() => setApproved(true)}>检查完成后通过 <ArrowRight size={19} weight="bold" /></button>
            </>}
          </div>
        </header>

        {tab !== "编辑" ? <StageView stage={tab} notify={notify} setTab={setTab} project={activeProject} activeSourceAssetId={activeSourceAssetId} setActiveSourceAssetId={setActiveSourceAssetId} pattern={activePattern && editedPattern ? {...activePattern, pattern: editedPattern} : activePattern} setProject={setActiveProject} onProjectsChanged={refreshProjects} boardLayout={boardLayout} setBoardLayout={saveBoardLayout} customBoardLayouts={availableCustomLayouts} hasSavedBoardPlan={Boolean(activeBoardPlan)} setActivePattern={(value) => { setActivePattern(value); setEditedPattern(value.pattern); latestEditRef.current = value.pattern; setActiveSourceAssetId(value.source_asset_id); setSelectedColor(value.pattern.palette?.[0] ? { code: value.pattern.palette[0].code, value: value.pattern.palette[0].value } : null); }} /> : <div className="work-area">
          <section className="editor">
            <div className="notice">
              <div><WarningCircle size={23} /><span>图纸检查发现 <strong>{inspection?.summary?.total ?? 0}</strong> 项待确认（无阻断项）</span></div>
              <button onClick={runInspection}>重新检查</button>
            </div>
            <div className="scroll">
              <div className="canvas">
                <div className="board-wrap">
                  {activePattern && editedPattern ? <PatternBoard key={`${activePattern.id}-${selectedVersion || "working"}`} zoom={zoom} setZoom={setZoom} result={{...activePattern, pattern: versionPreview || editedPattern}} tool={versionPreview ? "查看" : tool} selectedColor={selectedColor} setSelectedColor={setSelectedColor} onChange={(value) => { if (versionPreview) return; latestEditRef.current = value; setSaveState("有未保存修改"); setEditedPattern(value); }} editorApiRef={editorApi} viewOptions={viewOptions} inspectionIssue={versionPreview ? null : currentIssue} onBatchErase={(erased, box) => { if (!erased) { notify("所选区域没有可擦除的豆点"); return; } notify(`已批量擦除 ${erased} 颗豆点（${box.x1 + 1},${box.y1 + 1}–${box.x2 + 1},${box.y2 + 1}）；可撤销恢复`); }} /> : <div className="project-empty"><GridFour size={48}/><strong>没有可编辑图纸</strong><span>请先在“图纸”阶段生成并确认一个真实候选。</span></div>}
                  {versionPreview && <div className="version-overlay">历史版本只读预览 · 可恢复为新的工作副本</div>}
                </div>
              </div>

              <section className="suggestion inspection-card">
                <div className="suggestion-count">
                  <span>{currentIssue ? `问题 ${suggestion + 1} / ${inspection.issues.length}` : "检查完成"}</span>
                  <div><button disabled={!currentIssue || suggestion === 0} onClick={() => nextSuggestion(-1)}><CaretLeft size={18} /></button><button disabled={!currentIssue || suggestion >= inspection.issues.length - 1} onClick={() => nextSuggestion(1)}><CaretRight size={18} /></button></div>
                </div>
                <div className={`issue-badge ${currentIssue?.severity || "clear"}`}><ShieldCheck size={34} /><strong>{currentIssue?.type === "isolated_bead" ? "孤立豆" : currentIssue?.type === "similar_colors" ? "相近色" : currentIssue?.type === "low_outline_contrast" ? "轮廓" : currentIssue?.type === "board_seam_content" ? "分板线" : "通过"}</strong></div>
                <div className="suggestion-copy">
                  <h2>{currentIssue?.title || "当前图纸未发现需要确认的问题"}</h2>
                  <p>{currentIssue?.message || "可以继续保存关键版本或进入导出阶段。"}{currentIssue?.coordinates?.[0] && ` 定位：第 ${currentIssue.coordinates[0].x + 1} 列，第 ${currentIssue.coordinates[0].y + 1} 行。`}</p>
                </div>
                <div className="suggestion-actions">
                  <button className="primary" disabled={!currentIssue} onClick={() => { setTool("画笔"); notify("已定位问题，可使用编辑工具处理"); }}>定位并编辑</button>
                  <button className="outline" disabled={!currentIssue} onClick={() => { if (suggestion < inspection.issues.length - 1) setSuggestion(suggestion + 1); notify("已确认保留当前设计"); }}>保留并继续</button>
                </div>
              </section>
            </div>
          </section>

          <aside className="inspector">
            <Panel title="编辑工具" open={true} setOpen={() => {}}>
              <div className="tool-grid" aria-label="编辑工具">
                {[...tools, ...(extra ? extras : [])].map(([label, Icon, disabled]) => (
                  <button key={label} disabled={disabled} title={label} aria-label={label} className={tool === label ? "active" : ""} onClick={() => {
                    if (label === "撤销" || label === "重做") {
                      const changed = editorApi.current?.[label === "撤销" ? "undo" : "redo"]?.();
                      notify(changed ? `已${label}` : `没有可${label}的操作`);
                    } else if (label === "复制") {
                      const changed = editorApi.current?.copySelection?.();
                      notify(changed === "out-of-bounds" ? "复制区域会超出图板" : changed ? "已向右下复制所选区域" : "请先框选包含豆点的区域");
                    } else { setTool(label); notify(label === "批量擦除" ? "拖拽框选区域，松开后一次擦除；可用撤销恢复" : `已选择${label}工具`); }
                  }}>
                    <Icon size={20} weight={tool === label ? "fill" : "regular"} /><span>{label}</span>
                  </button>
                ))}
                <button className="expand-tools" onClick={() => setExtra(!extra)}><DotsNine size={20} /><span>{extra ? "收起" : "更多"}</span></button>
                <button className={tool === "平移" ? "active" : ""} onClick={() => { setTool("平移"); notify("拖动画布可平移视图"); }}><Hand size={20} /><span>平移</span></button>
              </div>
            </Panel>
            <Panel title="颜色方案" open={palette} setOpen={setPalette}>
              <div className="scheme-row"><span>{editedPattern ? `${editedPattern.colorMode || "标准"} · ${editedPattern.statistics.colorCount}色` : "等待真实图纸"}</span><button className="select" onClick={() => setScheme(!scheme)}>MARD <CaretDown size={13} /></button>
                {scheme && <div className="scheme-menu"><button onClick={() => setScheme(false)}>MARD</button><button onClick={() => notify("已切换至 HAMA 色库")}>HAMA</button><button onClick={() => notify("已切换至 PERLER 色库")}>PERLER</button></div>}
              </div>
              <div className="swatches">{(editedPattern?.palette || []).map((item) => <button className={selectedColor?.code === item.code ? "selected" : ""} key={item.code} aria-label={`选择色号 ${item.code}`} onClick={() => { setSelectedColor({code:item.code,value:item.value}); setTool("画笔"); notify(`已选择色号 ${item.code}`); }}><i style={{ backgroundColor: item.value }} /><span>{item.code}</span></button>)}</div>
              <button className="official-palette-toggle" onClick={() => setShowOfficialColors((open) => !open)}>{showOfficialColors ? "收起" : "展开"} MARD 全部色号 <span>{officialColors.length || 221} 色</span></button>
              {showOfficialColors && <div className="official-swatches" aria-label="MARD 官方全色号">{officialColors.map((item) => <button className={selectedColor?.code === item.code ? "selected" : ""} key={item.code} aria-label={`选择官方色号 ${item.code}`} onClick={() => { setSelectedColor(item); setTool("画笔"); notify(`已选择官方色号 ${item.code}，绘制到图纸后会加入颜色方案`); }}><i style={{ backgroundColor: item.value }} /><span>{item.code}</span></button>)}</div>}
            </Panel>
            <Panel title="图板" open={board} setOpen={setBoard}>
              <div className="board-label"><SquaresFour size={17} weight="fill" /> 当前图板（{editedPattern?.boardLayout?.boardWidth || 52} × {editedPattern?.boardLayout?.boardHeight || 52} × {editedPattern ? editedPattern.boardLayout.columns * editedPattern.boardLayout.rows : 0}）</div>
              <div className="marking-note"><span className="marking-sample" />标准定位标线 · 每 5 针</div>
              <div className="view-options">
                {[["codes","显示色号"],["coordinates","显示坐标"],["markings","显示标线"],["seams","显示分板线"]].map(([key,label]) => <label key={key}><input type="checkbox" checked={viewOptions[key]} onChange={() => setViewOptions((current) => ({...current,[key]:!current[key]}))} /><span>{label}</span></label>)}
              </div>
              <div className="board-grid">{[0, 1, 2, 3].map((item) => <button key={item} className={item === 0 ? "selected" : ""} onClick={() => notify(`已定位图板 ${item + 1}`)} />)}</div>
              <strong className="bean-count">{editedPattern ? `共 ${editedPattern.statistics.totalBeads.toLocaleString()} 颗` : "等待图纸"}</strong>
            </Panel>
            <div className={`autosave-state ${saveState.includes("失败") || saveState.includes("冲突") ? "error" : ""}`}><CheckCircle size={16} weight="fill" />{saveState}</div>
            <Panel title="版本记录" open={history} setOpen={setHistory} className="version-panel">
              <div className="versions">
                <button className={`version ${!selectedVersion ? "active" : ""}`} onClick={() => { setSelectedVersion(null); setVersionPreview(null); }}>
                  <div><strong>工作副本</strong><b>当前版本</b></div><span>修订 {activePattern?.pattern?.revision ?? 0} · 自动保存</span><i>{!selectedVersion && <Circle size={9} weight="fill" />}</i>
                </button>
                {versions.map((item) => <button className={`version ${selectedVersion === item.id ? "active" : ""}`} key={item.id} onClick={() => previewVersion(item)}>
                  <div><strong>V{item.version_no}</strong></div><span>{new Date(item.created_at).toLocaleString("zh-CN")} · {item.name}</span><i>{selectedVersion === item.id && <Circle size={9} weight="fill" />}</i>
                </button>)}
                {selectedVersion ? <button className="view-all" onClick={restoreVersion}>恢复所选版本 <ClockCounterClockwise size={15} /></button> : <button className="view-all" onClick={createVersion}>保存当前关键版本 <Plus size={15} /></button>}
              </div>
            </Panel>
          </aside>
        </div>}</>}
      </section>

      {toast && <div className="toast"><Check size={18} weight="bold" />{toast}</div>}
      {compare && <div className="backdrop" role="dialog" aria-modal="true">
        <div className="compare-modal">
          <div className="modal-head"><div><h2>原图与 2D 对比</h2><p>确认主体、比例和颜色关系后返回图纸编辑</p></div><button onClick={() => setCompare(false)}>关闭</button></div>
          <div className="compare-grid"><article><span>原始素材</span>{activeProject && projectOriginal ? <img src={api.assetContentUrl(activeProject.id, projectOriginal.id)} alt={`${activeProject.name}原始素材`} /> : <div className="source-placeholder"><ImageSquare size={48}/><span>暂无原始素材</span></div>}</article><article><span>已确认 2D 形象</span>{activeProject && projectTwoD ? <img src={api.assetContentUrl(activeProject.id, projectTwoD.id)} alt={`${activeProject.name}正式2D`} /> : <div className="source-placeholder"><ImageSquare size={48}/><span>暂无正式 2D</span></div>}</article></div>
          <button className="primary" onClick={() => setCompare(false)}>返回图纸编辑</button>
        </div>
      </div>}
      {approved && <div className="backdrop" role="dialog" aria-modal="true">
        <div className="approval-modal"><div className="success"><Check size={34} weight="bold" /></div><h2>图纸已通过审核</h2><p>当前 V3 版本将作为正式图纸，可继续进入导出设置。</p><div><button className="outline" onClick={() => setApproved(false)}>继续检查</button><button className="primary" onClick={() => { setApproved(false); setTab("导出"); notify("已进入导出设置"); }}>前往导出 <ArrowRight size={17} /></button></div></div>
      </div>}
      {auxPanel && <AuxiliaryPanel type={auxPanel} close={() => setAuxPanel("")} notify={notify} onCreate={createProject} onRestore={restoreBackup} project={activeProject} />}
    </main>
  );
}

function ProjectCenter({ filter, setFilter, search, setSearch, projects, archivedProjects, loading, error, onRetry, onOpen, onBackup, onNew, onPanel, onArchive }) {
  const displayed = filter === "已归档" ? archivedProjects : projects;
  const filtered = displayed.filter((item) => item.name.includes(search.trim()));
  return <section className="project-center">
    <header className="project-center-head">
      <div><span>项目工作区</span><h1>我的拼豆项目</h1><p>继续编辑、检查批量任务，或复用已经成功的图纸方案。</p></div>
      <button className="primary" onClick={onNew}><Plus size={18} weight="bold" />新建项目</button>
    </header>
    <div className="project-toolbar">
      <div className="project-filters">{folders.map((name) => <button className={filter === name ? "active" : ""} key={name} onClick={() => setFilter(name)}>{name}</button>)}</div>
      <label><MagnifyingGlass size={17} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索项目名称" /></label>
    </div>
    <div className="project-overview">
      <button onClick={() => onPanel("tasks")}><ListChecks size={22} /><span><strong>批量任务</strong><small>2 个处理中 · 1 个待重试</small></span><CaretRight size={17} /></button>
      <button onClick={() => onPanel("history")}><ClockCounterClockwise size={22} /><span><strong>最近版本</strong><small>今天新增 3 个关键版本</small></span><CaretRight size={17} /></button>
      <button onClick={() => onPanel("exports")}><DownloadSimple size={22} /><span><strong>导出记录</strong><small>本月已生成 18 个图纸包</small></span><CaretRight size={17} /></button>
    </div>
    <div className="project-list-head"><strong>本机项目</strong><span>{filtered.length} 个项目</span></div>
    <div className="project-grid">
      {loading && <div className="project-empty"><ArrowClockwise size={44} /><strong>正在读取本机项目</strong><span>请稍候。</span></div>}
      {!loading && error && <div className="project-empty"><WarningCircle size={44} /><strong>本机服务未连接</strong><span>{error}</span><button className="outline" onClick={onRetry}>重新连接</button></div>}
      {!loading && !error && filtered.map((item) => <article key={item.id} onContextMenu={(event) => { event.preventDefault(); void onArchive(item, !item.archived); }} title="右键归档或恢复">
        <button className="project-cover" onClick={() => onOpen(item)}><img src={item.assets.find((asset)=>asset.role==="original") ? api.assetContentUrl(item.id, item.assets.find((asset)=>asset.role==="original").id) : "/assets/project-thumb.png"} alt={item.name} /><span>{item.current_stage === "material" ? "素材" : item.current_stage}</span></button>
        <div className="project-card-body"><div><span className={`status ${item.archived ? "status-已归档" : "status-进行中"}`}>{item.archived ? "已归档" : "进行中"}</span><small>本机保存</small></div><h2>{item.name}</h2><p>{new Date(item.updated_at).toLocaleString("zh-CN")} 更新</p><div className="progress-line"><i style={{ width: item.assets.filter((asset) => !asset.archived).length ? "16%" : "4%" }} /></div><footer><button onClick={() => onBackup(item)}><DownloadSimple size={14} />备份</button><button onClick={() => void onArchive(item, !item.archived)}>{item.archived ? "恢复项目" : "归档项目"}</button><button onClick={() => onOpen(item)}>继续编辑 <ArrowRight size={14} /></button></footer></div>
      </article>)}
      {!loading && !error && filtered.length === 0 && <div className="project-empty"><Folder size={44} /><strong>{projects.length ? "没有找到匹配项目" : "还没有本机项目"}</strong><span>{projects.length ? "换一个关键词试试。" : "新建项目，或从 .perler.zip 备份恢复。"}</span></div>}
    </div>
  </section>;
}

function BatchPanel({ project, notify }) {
  const [assets, setAssets] = useState(project?.assets || []);
  const [selected, setSelected] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [layout, setLayout] = useState("quad");
  const [colorMode, setColorMode] = useState("standard");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const refresh = async () => {
    if (!project) return setJobs([]);
    try { setJobs((await api.listBatches(project.id)).items); } catch { setError("无法读取批量任务，请确认本机服务已启动。"); }
  };
  useEffect(() => {
    if (!project?.id) return;
    let active = true;
    api.listBatches(project.id)
      .then((result) => { if (active) setJobs(result.items); })
      .catch(() => { if (active) setError("无法读取批量任务，请确认本机服务已启动。"); });
    return () => { active = false; };
  }, [project?.id]);
  const toggle = (id) => setSelected((current) => current.includes(id) ? current.filter((value) => value !== id) : current.length < 10 ? [...current, id] : current);
  const mark2d = async (asset) => {
    setBusy(true); setError("");
    try {
      const updated = await api.updateAssetRole(project.id, asset.id, "confirmed_2d");
      setAssets((current) => current.map((item) => item.id === updated.id ? updated : item));
      notify(`${asset.original_name}已确认为正式 2D 素材`);
    } catch { setError("素材状态更新失败。"); } finally { setBusy(false); }
  };
  const create = async () => {
    if (selected.length < 2) return setError("请选择 2–10 张正式 2D 素材。");
    setBusy(true); setError("");
    try {
      await api.createBatch(project.id, selected, layout, colorMode);
      setSelected([]); await refresh(); notify("批量图纸生成完成");
    } catch (cause) {
      setError(cause instanceof Error && cause.message === "FORMAL_2D_REQUIRED" ? "批量任务只能使用已确认的正式 2D 素材。" : "批量任务创建失败，请检查素材文件。");
    } finally { setBusy(false); }
  };
  const retry = async (job) => {
    setBusy(true); setError("");
    try { await api.retryBatch(project.id, job.id); await refresh(); notify("失败项已按原始参数重新执行"); }
    catch { setError("当前批次没有可重试项目，或本机服务未连接。"); } finally { setBusy(false); }
  };
  const confirmAndExport = async (job) => {
    setBusy(true); setError("");
    try {
      const ids = job.items.filter((item) => item.status === "succeeded").map((item) => item.id);
      await api.confirmBatch(project.id, job.id, ids);
      const result = await api.createBatchExport(project.id, job.id);
      window.location.href = api.batchExportDownloadUrl(project.id, job.id);
      await refresh(); notify(`已生成 ${result.item_count} 份批量图纸包`);
    } catch { setError("批量确认或导出失败。"); } finally { setBusy(false); }
  };
  if (!project) return <div className="aux-list"><div className="project-empty"><ListChecks size={42}/><strong>请先打开一个项目</strong><span>批量任务按项目管理。</span></div></div>;
  const statusText = { queued: "排队中", running: "处理中", partial_failed: "部分失败", succeeded: "已完成", failed: "失败", canceled: "已取消" };
  return <div className="batch-panel">
    <section className="batch-create">
      <div className="batch-section-title"><strong>选择正式 2D 素材</strong><span>{selected.length} / 10</span></div>
      <p>批量范围为 2–10 张；尚未确认的图片需先标记为已处理 2D。</p>
      <div className="batch-assets">{assets.map((asset) => <article key={asset.id} className={selected.includes(asset.id) ? "selected" : ""}>
        <button className="batch-thumb" disabled={asset.role !== "confirmed_2d"} onClick={() => toggle(asset.id)}>
          <img src={api.assetContentUrl(project.id, asset.id)} alt="" />
          <span>{selected.includes(asset.id) ? <Check size={13} weight="bold"/> : asset.sequence_no}</span>
        </button>
        <strong title={asset.original_name}>{asset.original_name}</strong>
        {asset.role === "confirmed_2d" ? <small>正式 2D</small> : <button disabled={busy} onClick={() => mark2d(asset)}>确认为 2D</button>}
      </article>)}</div>
      <div className="batch-options">
        <label>图板<select value={layout} onChange={(event) => setLayout(event.target.value)}><option value="single">单板</option><option value="double_horizontal">横向双板</option><option value="double_vertical">纵向双板</option><option value="quad">四联板</option><option value="six_horizontal">六联板</option></select></label>
        <label>配色<select value={colorMode} onChange={(event) => setColorMode(event.target.value)}><option value="limited">少色</option><option value="standard">标准</option><option value="rich">丰富</option></select></label>
      </div>
      <button className="primary" disabled={busy || selected.length < 2} onClick={create}>{busy ? "正在处理…" : `生成所选 ${selected.length || 0} 张图纸`}</button>
    </section>
    {error && <p className="form-error batch-error">{error}</p>}
    <section className="aux-list batch-jobs">
      <div className="batch-section-title"><strong>任务队列</strong><span>{jobs.length} 个批次</span></div>
      {jobs.map((job) => {
        const succeeded = job.items.filter((item) => item.status === "succeeded").length;
        const failed = job.items.filter((item) => item.status === "failed").length;
        return <article key={job.id}><div><strong>批次 {job.id.slice(0, 8)}</strong><span>{statusText[job.status] || job.status}</span></div>
          <p>{succeeded}/{job.items.length} 成功{failed ? ` · ${failed} 项待重试` : ""} · {job.color_mode} / {job.board_layout}</p>
          <i><b style={{ width: `${Math.round((succeeded + failed) / job.items.length * 100)}%` }} /></i>
          <div className="batch-actions">{failed > 0 && <button disabled={busy} onClick={() => retry(job)}>重试失败项</button>} {succeeded > 0 && <button disabled={busy} onClick={() => confirmAndExport(job)}>批量确认并导出</button>}</div>
        </article>;
      })}
      {!jobs.length && <div className="batch-empty">还没有批量任务。</div>}
    </section>
  </div>;
}

function AuxiliaryPanel({ type, close, notify, onCreate, onRestore, project }) {
  const [name, setName] = useState("未命名拼豆项目");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const backupInput = useRef(null);
  const run = async (action) => {
    setBusy(true); setError("");
    try { await action(); } catch (cause) {
      const code = cause instanceof Error ? cause.message : "";
      setError(code === "BACKUP_INVALID" ? "备份包无效或文件已损坏。" : "操作失败，请确认本机数据服务已经启动。");
    } finally { setBusy(false); }
  };
  const title = { new: "新建拼豆项目", tasks: "批量任务", history: "完整版本记录", exports: "导出记录", settings: "工作台设置" }[type];
  return <div className="backdrop aux-backdrop" role="dialog" aria-modal="true">
    <section className="aux-panel">
      <header><div><span>项目辅助功能</span><h2>{title}</h2></div><button onClick={close} aria-label="关闭"><X size={20} /></button></header>
      {type === "new" && <div className="new-project-form">
        <label>项目名称<input value={name} onChange={(event) => setName(event.target.value)} /></label>
        <label>保存分类<select defaultValue="新设计"><option>新设计</option><option>热卖款</option><option>季节限定</option></select></label>
        <fieldset><legend>开始方式</legend><button className="active"><UploadSimple size={22} /><strong>导入素材</strong><span>从原图开始完整流程</span></button><button><Copy size={22} /><strong>复制成功方案</strong><span>复用图板与配色设置</span></button></fieldset>
        {error && <p className="form-error">{error}</p>}
        <button className="primary aux-primary" disabled={busy || !name.trim()} onClick={() => run(() => onCreate(name.trim()))}>{busy ? "正在创建…" : "创建并添加素材"} <ArrowRight size={17} /></button>
        <input ref={backupInput} type="file" accept=".zip,.perler.zip,application/zip" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void run(() => onRestore(file)); }} />
        <button className="outline aux-primary" disabled={busy} onClick={() => backupInput.current?.click()}><ClockCounterClockwise size={17} />从项目备份恢复</button>
      </div>}
      {type === "tasks" && <BatchPanel project={project} notify={notify} />}
      {type === "history" && <div className="aux-list version-log">
        {[["V3", "自动优化与建议", "今天 10:24", "当前正式版本"], ["V2", "调整配色方案", "今天 09:47", "12 色 → 9 色"], ["V1", "生成标准图纸", "昨天 16:30", "首次生成"], ["2D-03", "确认 2D 候选 B", "昨天 15:52", "正式 2D 资产"]].map(([id, action, time, note]) => <article key={id}><div><strong>{id} · {action}</strong><span>{time}</span></div><p>{note}</p><button onClick={() => notify(`已打开 ${id} 对比视图`)}>查看与对比</button></article>)}
      </div>}
      {type === "exports" && <div className="aux-list export-log">
        {[["柠檬宝宝_正式图纸包.zip", "今天 11:06", "PDF + PNG · 18.4 MB"], ["柠檬宝宝_社媒展示图.png", "今天 10:58", "竖版 3:4 · 2.1 MB"], ["迷你蔬菜胸针_分板图.zip", "7 月 23 日", "4 张 PNG · 9.8 MB"]].map(([name, time, meta]) => <article key={name}><div><strong>{name}</strong><span>{time}</span></div><p>{meta}</p><button onClick={() => notify("下载已开始")}>再次下载</button></article>)}
      </div>}
      {type === "settings" && <div className="settings-form">
        <label><span><strong>默认拼豆品牌</strong><small>新项目自动选择的品牌色库</small></span><select defaultValue="MARD"><option>MARD</option><option>HAMA</option><option>PERLER</option></select></label>
        <label><span><strong>默认拼豆规格</strong><small>用于尺寸与用量计算</small></span><select defaultValue="5 mm"><option>5 mm</option><option>2.6 mm</option></select></label>
        <label><span><strong>自动保存关键版本</strong><small>确认 2D、图纸与导出前自动留档</small></span><input type="checkbox" defaultChecked /></label>
        <button className="primary aux-primary" onClick={() => { notify("设置已保存"); close(); }}>保存设置</button>
      </div>}
    </section>
  </div>;
}

const stageData = {
  "素材": { eyebrow: "步骤 1 / 6", title: "整理生成素材", desc: "上传原图并确认主体，为 2D 形象生成做好准备。", action: "添加素材" },
  "2D": { eyebrow: "步骤 2 / 6", title: "确认 2D 形象", desc: "从候选中确认主体造型、比例和细节，颜色暂不受真实色号限制。", action: "生成新候选" },
  "图板": { eyebrow: "步骤 3 / 6", title: "规划图板与构图", desc: "选择标准图板组合，确认成品尺寸、主体占比和拼接线位置。", action: "自动推荐图板" },
  "图纸": { eyebrow: "步骤 4 / 6", title: "选择图纸候选", desc: "比较颜色数量、总豆数与图纸差异，确定进入编辑的版本。", action: "生成候选图纸" },
  "导出": { eyebrow: "步骤 6 / 6", title: "导出正式图纸包", desc: "检查图纸、图例和分板文件，生成可制作或用于商品交付的文件。", action: "开始导出" },
};

function StageView({ stage, notify, setTab, project, activeSourceAssetId, setActiveSourceAssetId, pattern, setProject, onProjectsChanged, setActivePattern, boardLayout, setBoardLayout, customBoardLayouts = [], hasSavedBoardPlan = false }) {
  if (stage === "素材") return <MaterialStage notify={notify} project={project} setProject={setProject} onProjectsChanged={onProjectsChanged} onNext={() => setTab("2D")} />;
  if (stage === "2D") return <TwoDStage notify={notify} project={project} activeSourceAssetId={activeSourceAssetId} setActiveSourceAssetId={setActiveSourceAssetId} setProject={setProject} onNext={() => setTab("图板")} />;
  if (stage === "图板") return <BoardStage notify={notify} project={project} activeSourceAssetId={activeSourceAssetId} setActiveSourceAssetId={setActiveSourceAssetId} boardLayout={boardLayout} setBoardLayout={setBoardLayout} onNext={() => setTab("图纸")} />;
  if (stage === "图纸") return <PatternCandidateStage notify={notify} project={project} activeSourceAssetId={activeSourceAssetId} setActiveSourceAssetId={setActiveSourceAssetId} boardLayout={boardLayout} setBoardLayout={setBoardLayout} customBoardLayouts={customBoardLayouts} hasSavedBoardPlan={hasSavedBoardPlan} onNext={() => setTab("编辑")} setActivePattern={setActivePattern} />;
  if (stage === "导出") return <ExportStage notify={notify} project={project} result={pattern} />;
  const data = stageData[stage] || stageData["素材"];
  const cards = stage === "素材"
    ? [["原始图片", "已上传 · 2048 × 2048", "project-thumb.png"], ["去背预览", "主体识别完成", "project-thumb.png"], ["素材检查", "清晰度良好 · 单主体", null]]
    : stage === "2D"
    ? [["候选 A", "系统推荐 · 细节完整", "lemon-board.png"], ["候选 B", "轮廓更简洁", "lemon-board.png"], ["候选 C", "表情更突出", "lemon-board.png"]]
    : stage === "图板"
    ? [["四联图板", "52 × 52 × 4 · 520 × 520 mm", null], ["六联图板", "52 × 52 × 6 · 780 × 520 mm", null], ["自定义组合", "按标准单板数量规划", null]]
    : stage === "图纸"
    ? [["少色方案", "7 色 · 1,438 颗", "lemon-board.png"], ["标准方案", "12 色 · 1,476 颗", "lemon-board.png"], ["丰富方案", "18 色 · 1,492 颗", "lemon-board.png"]]
    : [["完整图纸 PDF", "总图、坐标、色号图例", null], ["分板图 PNG", "A1–B2 共 4 张", null], ["商品展示图", "竖版社媒图 3 张", null]];
  return <section className="stage-page">
    <div className="stage-heading"><div><span>{data.eyebrow}</span><h1>{data.title}</h1><p>{data.desc}</p></div><button className="primary" onClick={() => notify(`${data.action}面板已打开`)}><Plus size={17} />{data.action}</button></div>
    <div className="stage-progress">{topTabs.map((item, index) => <button key={item} className={item === stage ? "active" : ""} onClick={() => setTab(item)}><b>{index + 1}</b><span>{item}</span></button>)}</div>
    <div className="stage-cards">{cards.map(([title, meta, image], index) => <article className={index === 1 ? "selected" : ""} key={title} onClick={() => notify(`已选择${title}`)}>
      <div className={`stage-preview ${image ? "has-image" : ""}`}>{image ? <img src={`/assets/${image}`} alt="" /> : stage === "图板" ? <div className="mini-board">{Array.from({length:index === 1 ? 6 : 4},(_,n)=><i key={n}/>)}</div> : <FileText size={42} />}</div>
      <div><h3>{title}</h3><p>{meta}</p></div><button>{index === 1 ? "已选择" : "选择"}</button>
    </article>)}</div>
    <div className="stage-bottom"><div><WarningCircle size={20}/><span>{stage === "导出" ? "导出前将检查文件完整性" : "所有调整会自动保存为项目草稿"}</span></div><button className="primary" onClick={() => setTab(stage === "导出" ? "导出" : topTabs[topTabs.indexOf(stage)+1])}>{stage === "导出" ? "确认导出" : "确认并继续"}<ArrowRight size={17}/></button></div>
  </section>
}

function AssetPicker({ project, value, onChange, onlyFormal = false }) {
  const assets = (project?.assets || []).filter((asset) => !asset.archived && (!onlyFormal || asset.role === "confirmed_2d"));
  if (!assets.length) return <div className="asset-picker empty">请先确认一张正式 2D</div>;
  return <label className="asset-picker"><span>当前处理素材</span><select value={value || ""} onChange={(event) => onChange(event.target.value)}>{assets.map((asset) => <option value={asset.id} key={asset.id}>{asset.original_name.replace(/^\[直导2D\] /, "")}</option>)}</select></label>;
}

function ExportStage({ notify, project, result }) {
  const [active, setActive] = useState("完整图纸");
  const [mirrorPreview, setMirrorPreview] = useState(false);
  const [includeMirroredPattern, setIncludeMirroredPattern] = useState(false);
  const [selected, setSelected] = useState(["完整图纸", "分板图", "色号用量表", "制作说明"]);
  const [format, setFormat] = useState("PDF + PNG");
  const [watermarkTemplates, setWatermarkTemplates] = useState(() => {
    if (typeof window === "undefined") return DEFAULT_WATERMARK_TEMPLATES;
    try { const saved = JSON.parse(window.localStorage.getItem("perler-watermark-templates") || "null"); return Array.isArray(saved) && saved.length === 3 ? saved : DEFAULT_WATERMARK_TEMPLATES; } catch { return DEFAULT_WATERMARK_TEMPLATES; }
  });
  const [activeWatermarkTemplate, setActiveWatermarkTemplate] = useState(0);
  const [watermark, setWatermark] = useState(() => ({ ...DEFAULT_WATERMARK_TEMPLATES[0], enabled: true }));
  const watermarkPreviewRef = useRef(null);
  const watermarkDragRef = useRef(false);
  const [quality, setQuality] = useState("高清");
  const [exported, setExported] = useState(null);
  const [exporting, setExporting] = useState(false);
  useEffect(() => { setWatermark({ ...watermarkTemplates[activeWatermarkTemplate], enabled: true }); }, [activeWatermarkTemplate]);
  const updateWatermark = (updater) => setWatermark((current) => typeof updater === "function" ? updater(current) : updater);
  const saveWatermarkTemplate = () => {
    const next = watermarkTemplates.map((item, index) => index === activeWatermarkTemplate ? { ...watermark, enabled: true } : item);
    setWatermarkTemplates(next);
    window.localStorage.setItem("perler-watermark-templates", JSON.stringify(next));
    notify(`模板 ${activeWatermarkTemplate + 1} 已保存`);
  };
  const pattern = result?.pattern;
  const boardIds = pattern ? Array.from({ length: pattern.boardLayout.rows }, (_, row) =>
    Array.from({ length: pattern.boardLayout.columns }, (_, column) => `${String.fromCharCode(65 + row)}${column + 1}`),
  ).flat() : [];
  const projectName = project?.name || "未打开项目";
  const sourceAsset = project?.assets?.find((asset) => asset.id === result?.source_asset_id);
  const revision = pattern?.revision ?? 0;
  const boardLabel = pattern ? `${pattern.width} × ${pattern.height} 针` : "等待真实图纸";
  const files = [
    { id: "完整图纸", meta: "PDF / PNG · 带坐标与色号", icon: FileText },
    { id: "分板图", meta: `PNG · 共 ${boardIds.length} 张`, icon: SquaresFour },
    { id: "色号用量表", meta: `PDF / CSV · ${pattern?.statistics.colorCount || 0} 色`, icon: ShareNetwork },
    { id: "制作说明", meta: "PDF · 尺寸与拼接说明", icon: Ruler },
    { id: "图纸数据", meta: "JSON · 可追溯修订", icon: ImageSquare },
  ];
  const toggle = (id) => {
    setSelected((items) => items.includes(id) ? items.filter((x) => x !== id) : [...items, id]);
    setExported(false);
  };
  const activeFile = files.find((item) => item.id === active) || files[0];
  const createExport = async () => {
    if (!project || !result || !pattern) return notify("请先打开并保存真实图纸");
    setExporting(true);
    try {
      const created = await api.createPatternExport(project.id, result.id, revision, watermark, includeMirroredPattern);
      setExported(created);
      notify("正式图纸包生成完成");
    } catch (error) {
      notify(error instanceof Error && error.message === "PATTERN_VERSION_CONFLICT" ? "图纸已更新，请等待自动保存后重试" : "导出失败，请检查本机数据服务");
    } finally {
      setExporting(false);
    }
  };
  return <div className="export-stage">
    <aside className="export-files">
      <div className="stage-title"><span>06 / 导出交付</span><h1>生成正式图纸包</h1><p>选择交付文件，检查内容后统一导出。</p></div>
      <div className="export-project"><img src={sourceAsset ? api.assetContentUrl(project.id, sourceAsset.id) : "/assets/project-thumb.png"} alt="" /><div><strong>{projectName}</strong><span>修订 {revision} · {boardIds.length} 块图板 · MARD</span></div></div>
      <div className="option-head"><strong>交付内容</strong><button onClick={() => setSelected(files.map(x => x.id))}>全部选择</button></div>
      <div className="export-file-list">{files.map(({ id, meta, icon: Icon }) => {
        const checked = selected.includes(id);
        return <button key={id} className={`${active === id ? "active" : ""} ${checked ? "checked" : ""}`} onClick={() => setActive(id)}>
          <span className="file-check" onClick={(e) => { e.stopPropagation(); toggle(id); }}>{checked && <Check size={12} weight="bold" />}</span>
          <Icon size={20} weight={active === id ? "fill" : "regular"} />
          <span><strong>{id}</strong><small>{meta}</small></span>
          <CaretRight size={15} />
        </button>;
      })}</div>
      <section className="export-tip"><ShieldCheck size={19} weight="fill" /><div><strong>完整图纸可按需加水印或镜像</strong><p>水印写入完整图纸 PNG 与 PDF；开启镜像后会额外导出一份左右镜像参考图。</p></div></section>
    </aside>

    <section className="export-preview">
      <header className="preview-head"><div><h2>{activeFile.id}预览</h2><span>{projectName} · 当前修订 {revision}</span></div>{active === "完整图纸" && <div className="pattern-view-switch pattern-view-switch-header" role="group" aria-label="图纸预览模式"><button className={!mirrorPreview ? "active" : ""} onClick={() => setMirrorPreview(false)}>正常图纸</button><button className={mirrorPreview ? "active" : ""} onClick={() => setMirrorPreview(true)}>镜像图纸预览</button></div>}<div className="preview-tools"><button onClick={() => notify("预览已适应窗口")}><ArrowsOutLineHorizontal size={16} />适应窗口</button><button onClick={() => notify("可在编辑页放大检查真实网格")}><MagnifyingGlass size={16} />放大检查</button></div></header>
      <div className={`export-paper export-${activeFile.id}`}>
        {active === "完整图纸" && <><div className="pattern-view-switch"><button className={!mirrorPreview ? "active" : ""} onClick={() => setMirrorPreview(false)}>正常图纸</button><button className={mirrorPreview ? "active" : ""} onClick={() => setMirrorPreview(true)}>镜像图纸预览</button></div><div className="paper-sheet watermark-paper" ref={watermarkPreviewRef}><div className="paper-title"><strong>{projectName} · {mirrorPreview ? "镜像拼豆图纸" : "拼豆图纸"}</strong><span>{boardLabel} / MARD / 5 mm{mirrorPreview ? " / 左右镜像" : ""}</span></div><div className="paper-board">{result ? <GeneratedPatternPreview result={result} mirror={mirrorPreview} /> : <GridFour size={70} />}</div><div className="paper-legend">{(pattern?.palette || []).map((item) => <span key={item.code}><i style={{background:item.value}} />{item.code}-{item.count}</span>)}</div><small>{boardIds.join("–") || "无分板"} · 图例格式为“色号-数量”</small>{watermark.enabled && watermark.text && <button type="button" className="watermark-preview" style={{ left: `${watermark.x}%`, top: `${watermark.y}%`, color: watermark.color, opacity: watermark.opacity / 100, fontSize: `${Math.max(10, watermark.size / 5)}px`, fontFamily: watermark.font === "serif" ? "Georgia, serif" : watermark.font === "mono" ? "ui-monospace, monospace" : watermark.font === "rounded" ? "Arial Rounded MT Bold, PingFang SC, sans-serif" : watermark.font === "elegant" ? "Baskerville, Songti SC, serif" : watermark.font === "italic" ? "Kaiti SC, Times New Roman, serif" : watermark.font === "handwritten" ? "Kaiti SC, STKaiti, cursive" : "inherit", fontStyle: watermark.font === "italic" || watermark.font === "handwritten" ? "italic" : "normal", fontWeight: watermark.font === "bold" || watermark.font === "rounded" ? 800 : 600, transform: `translate(-50%, -50%) rotate(${watermark.rotation}deg)` }} onPointerDown={(event) => { event.currentTarget.setPointerCapture(event.pointerId); watermarkDragRef.current = true; }} onPointerMove={(event) => { if (!watermarkDragRef.current || !watermarkPreviewRef.current) return; const bounds = watermarkPreviewRef.current.getBoundingClientRect(); setWatermark((value) => ({ ...value, x: Math.max(0, Math.min(100, (event.clientX - bounds.left) / bounds.width * 100)), y: Math.max(0, Math.min(100, (event.clientY - bounds.top) / bounds.height * 100)) })); }} onPointerUp={() => { watermarkDragRef.current = false; }} aria-label="拖动调整水印位置">{watermark.text}</button>}</div></>}
        {active === "分板图" && <div className="split-sheets">{boardIds.map((id, index) => {
          const columns = pattern?.boardLayout?.columns || 1, boardWidth = pattern?.boardLayout?.boardWidth || 52, boardHeight = pattern?.boardLayout?.boardHeight || 52;
          const row = Math.floor(index / columns), column = index % columns;
          const bounds = { x1: column * boardWidth, y1: row * boardHeight, x2: Math.min((column + 1) * boardWidth, pattern.width), y2: Math.min((row + 1) * boardHeight, pattern.height) };
          return <article key={id}><b>{id}</b>{result ? <GeneratedPatternPreview result={result} bounds={bounds} /> : <GridFour size={42} />}<span>{bounds.x2-bounds.x1} × {bounds.y2-bounds.y1} 针</span></article>;
        })}</div>}
        {active === "色号用量表" && <div className="color-sheet"><header><strong>MARD 色号与用量</strong><span>共 {pattern?.statistics.colorCount || 0} 色 · {(pattern?.statistics.totalBeads || 0).toLocaleString()} 颗</span></header>{(pattern?.palette || []).map((item) => <div key={item.code}><i style={{background:item.value}} /><b>{item.code}</b><span>{item.value}</span><strong>{item.count} 颗</strong></div>)}</div>}
        {active === "制作说明" && <div className="instruction-sheet"><h2>制作说明</h2><div className="instruction-hero"><img src={project?.assets?.find((asset)=>asset.role==="original") ? api.assetContentUrl(project.id, project.assets.find((asset)=>asset.role==="original").id) : "/assets/project-thumb.png"} alt="" /><div><strong>成品尺寸</strong><span>约 {pattern?.statistics.physicalWidthMm || 0} × {pattern?.statistics.physicalHeightMm || 0} mm</span><strong>图板组合</strong><span>{pattern?.boardLayout?.boardWidth || 52} × {pattern?.boardLayout?.boardHeight || 52} 针 × {boardIds.length}</span></div></div>{[`按 ${boardIds.join("、") || "分板编号"} 顺序准备图板`,"逐格核对色点与 MARD 色号","完成后按蓝色拼接边界组合","熨烫前再次核对总豆数与缺豆"].map((x,i)=><p key={x}><b>{i+1}</b>{x}</p>)}</div>}
        {active === "图纸数据" && <div className="instruction-sheet"><h2>Pattern JSON</h2><p><b>1</b>Schema {pattern?.schemaVersion || "—"}</p><p><b>2</b>修订 {revision}</p><p><b>3</b>{pattern?.cells?.length || 0} 个已占用坐标</p><p><b>4</b>清单包含每个文件的 SHA-256 校验值</p></div>}
      </div>
      <footer className="export-preview-footer"><div><Eye size={18} /><span>当前预览：{activeFile.meta}</span></div><button className="outline" onClick={() => notify(`${activeFile.id}已单独保存预览`)}>保存此项预览</button></footer>
    </section>

    <aside className="export-inspector">
      <section className="config-card"><div className="card-heading"><strong>导出设置</strong><span>{selected.length} / {files.length} 项已选择</span></div>
        <label className="export-field">文件组合<select value={format} onChange={(e)=>setFormat(e.target.value)}><option>PDF + PNG</option><option>仅 PDF</option><option>仅 PNG</option></select></label>
        <label className="export-field">图片质量<div className="segment">{["标准","高清","印刷级"].map(v=><button key={v} className={quality===v?"active":""} onClick={()=>setQuality(v)}>{v}</button>)}</div></label>
        <label className="export-field">图纸比例<select defaultValue="原始尺寸"><option>原始尺寸</option><option>A4 适应页面</option><option>A3 适应页面</option></select></label>
        <label className="switch-line"><span><b>同时导出镜像完整图纸</b><small>适用于反面熨烫；导出包另含镜像 PNG 与 PDF</small></span><input type="checkbox" checked={includeMirroredPattern} onChange={(event)=>setIncludeMirroredPattern(event.target.checked)} /><i /></label>
        <label className="switch-line"><span><b>完整图纸加水印</b><small>默认使用模板 1，写入完整图纸 PNG 与 PDF</small></span><input type="checkbox" checked={watermark.enabled} onChange={(event)=>updateWatermark((value)=>({...value, enabled:event.target.checked}))} /><i /></label>
        {watermark.enabled && <div className="watermark-config">
          <div className="watermark-template-head"><strong>水印模板</strong><button onClick={saveWatermarkTemplate}>保存当前模板</button></div>
          <div className="watermark-templates">{[0,1,2].map((index) => <button key={index} className={activeWatermarkTemplate === index ? "active" : ""} onClick={() => setActiveWatermarkTemplate(index)}>模板 {index + 1}</button>)}</div>
          <label className="export-field">水印文字<input value={watermark.text} maxLength={100} placeholder="例如：@我的拼豆店" onChange={(event)=>updateWatermark((value)=>({...value, text:event.target.value}))} /></label>
          <label className="export-field">文字颜色<div className="watermark-color"><input type="color" value={watermark.color} onChange={(event)=>updateWatermark((value)=>({...value, color:event.target.value}))} /><code>{watermark.color.toUpperCase()}</code></div></label>
          <label className="export-field">字体<select value={watermark.font} onChange={(event)=>updateWatermark((value)=>({...value, font:event.target.value}))}><option value="sans">现代无衬线</option><option value="rounded">圆润可爱</option><option value="serif">经典衬线</option><option value="elegant">优雅书卷</option><option value="italic">斜体文艺</option><option value="handwritten">手写感</option><option value="bold">醒目粗体</option><option value="mono">等宽字体</option></select></label>
          <label className="export-field watermark-range">字号 <b>{watermark.size} px</b><input type="range" min="12" max="1600" step="4" value={watermark.size} onChange={(event)=>updateWatermark((value)=>({...value, size:Number(event.target.value)}))} /><small>最大 1600 px，接近一块 52×52 单板的高度。</small></label>
          <label className="export-field watermark-range">透明度 <b>{watermark.opacity}%</b><input type="range" min="0" max="100" value={watermark.opacity} onChange={(event)=>updateWatermark((value)=>({...value, opacity:Number(event.target.value)}))} /></label>
          <label className="export-field watermark-range">旋转方向 <b>{watermark.rotation}°</b><input type="range" min="0" max="360" step="1" value={watermark.rotation} onChange={(event)=>updateWatermark((value)=>({...value, rotation:Number(event.target.value)}))} /></label>
          <p className="watermark-help"><Hand size={14} />在中间预览里直接拖动水印调整位置。编辑后点击“保存当前模板”，下次导出可直接复用。</p>
        </div>}
      </section>
      <section className="config-card export-summary"><div className="card-heading"><strong>文件摘要</strong><span>{exported ? `${(exported.size_bytes / 1024 / 1024).toFixed(1)} MB` : "生成后计算"}</span></div><dl className="board-summary"><div><dt>项目</dt><dd>{projectName}</dd></div><div><dt>修订</dt><dd>{revision}</dd></div><div><dt>图板</dt><dd>{boardLabel}</dd></div><div><dt>色库</dt><dd>MARD · {pattern?.statistics.colorCount || 0} 色</dd></div><div><dt>总豆数</dt><dd>{(pattern?.statistics.totalBeads || 0).toLocaleString()} 颗</dd></div></dl></section>
      <section className="config-card export-check"><div className="config-title"><ShieldCheck size={21} weight="fill" /><div><strong>完整性检查通过</strong><span>单张导出仅提示，不阻止导出</span></div></div>{["正式图纸与格内色号完整","A1–B2 分板文件完整","色号表与总豆数一致","文件名无重复"].map(x=><p key={x}><CheckCircle size={16} weight="fill" />{x}</p>)}</section>
      <section className={`config-card export-action ${exported?"done":""}`}>{exported ? <><div className="export-done"><CheckCircle size={29} weight="fill" /><div><strong>图纸包已生成</strong><span>{exported.file_count} 个文件 · 修订 {exported.revision}</span></div></div><a className="primary" href={api.exportDownloadUrl(project.id, result.id, exported.revision)} download={exported.filename} onClick={()=>notify("下载任务已开始")}><Export size={17} />下载图纸包</a></> : <><strong>准备导出</strong><span>将生成 PDF、PNG、CSV、JSON 与校验清单。</span><button className="primary" disabled={!selected.length || !pattern || exporting} onClick={createExport}><Export size={17} />{exporting ? "正在生成…" : "生成并导出"}</button></>}</section>
    </aside>
  </div>;
}

function GeneratedPatternPreview({ result, bounds = null, showAxes = true, mirror = false }) {
  const { width, height, cells } = result.pattern;
  const area = bounds || { x1: 0, y1: 0, x2: width, y2: height };
  const visibleWidth = area.x2 - area.x1, visibleHeight = area.y2 - area.y1;
  const margin = showAxes ? 18 : 0;
  const scale = Math.min(720 / visibleWidth, 580 / visibleHeight);
  const cellSize = Math.max(5, scale);
  const guideLineWidth = Math.max(.85, cellSize * .12);
  const visibleCells = cells.filter((cell) => cell.x >= area.x1 && cell.x < area.x2 && cell.y >= area.y1 && cell.y < area.y2);
  return <svg
    className="generated-pattern-svg"
    viewBox={`0 0 ${visibleWidth * cellSize + margin} ${visibleHeight * cellSize + margin}`}
    role="img"
    aria-label={`真实生成图纸，${visibleWidth}×${visibleHeight}针`}
  >
    <rect width="100%" height="100%" fill="#fff" />
    {Array.from({length: visibleWidth + 1}, (_, n) => { const gridX = area.x1 + n; const locator = gridX > 0 && gridX % 5 === 0; return <line key={`gv-${n}`} x1={margin + n * cellSize} x2={margin + n * cellSize} y1={margin} y2={margin + visibleHeight * cellSize} stroke={locator ? gridX % 10 === 0 ? "#805ad5" : "#dd7777" : "#d9dee8"} strokeWidth={locator ? guideLineWidth : ".35"}/>; })}
    {Array.from({length: visibleHeight + 1}, (_, n) => { const gridY = area.y1 + n; const locator = gridY > 0 && gridY % 5 === 0; return <line key={`gh-${n}`} y1={margin + n * cellSize} y2={margin + n * cellSize} x1={margin} x2={margin + visibleWidth * cellSize} stroke={locator ? gridY % 10 === 0 ? "#805ad5" : "#dd7777" : "#d9dee8"} strokeWidth={locator ? guideLineWidth : ".35"}/>; })}
    {visibleCells.map((cell) => { const displayX = mirror ? visibleWidth - 1 - (cell.x - area.x1) : cell.x - area.x1; return <g key={`${cell.x}-${cell.y}`}>
      <rect x={margin + displayX * cellSize} y={margin + (cell.y - area.y1) * cellSize} width={cellSize} height={cellSize} fill={cell.colorValue} />
      {cellSize >= 6 && <text x={margin + (displayX + .5) * cellSize} y={margin + (cell.y - area.y1 + .68) * cellSize} textAnchor="middle" fontSize={Math.max(2.4, cellSize * .29)} fill="#17212b">{cell.colorCode}</text>}
    </g>; })}
    {showAxes && Array.from({length: visibleWidth}, (_, n) => (n === 0 || (n + 1) % 5 === 0 || n === visibleWidth - 1) && <text key={`ax-${n}`} x={margin + (n + .5) * cellSize} y="12" textAnchor="middle" fontSize="7" fill="#647684">{mirror ? area.x1 + visibleWidth - n : area.x1 + n + 1}</text>)}
    {showAxes && Array.from({length: visibleHeight}, (_, n) => (n === 0 || (n + 1) % 5 === 0 || n === visibleHeight - 1) && <text key={`ay-${n}`} x="11" y={margin + (n + .7) * cellSize} textAnchor="middle" fontSize="7" fill="#647684">{area.y1 + n + 1}</text>)}
    {(result.pattern.boardLayout.seamsX || []).filter((seam) => seam > area.x1 && seam < area.x2).map((seam) => { const displaySeam = mirror ? visibleWidth - (seam - area.x1) : seam - area.x1; return <line key={`x-${seam}`} x1={margin + displaySeam * cellSize} x2={margin + displaySeam * cellSize} y1={margin} y2={margin + visibleHeight * cellSize} stroke="#1687d9" strokeWidth="1.5" />; })}
    {(result.pattern.boardLayout.seamsY || []).filter((seam) => seam > area.y1 && seam < area.y2).map((seam) => <line key={`y-${seam}`} y1={margin + (seam-area.y1) * cellSize} y2={margin + (seam-area.y1) * cellSize} x1={margin} x2={margin + visibleWidth * cellSize} stroke="#1687d9" strokeWidth="1.5" />)}
  </svg>;
}

function StageVersionMenu({ project, stage, label, snapshot, onRestore }: { project: any; stage: "twod" | "board" | "pattern" | "editor"; label: string; snapshot: Record<string, any>; onRestore: (snapshot: any) => void }) {
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState(null);
  const [open, setOpen] = useState(false);
  const refresh = async () => {
    if (!project) return;
    const result = await api.listStageVersions(project.id, stage);
    setItems(result.items);
  };
  useEffect(() => { void refresh().catch(() => setItems([])); }, [project?.id, stage]);
  const save = async () => {
    if (!project) return;
    const created = await api.createStageVersion(project.id, stage, `${label} V${(items[0]?.version_no || 0) + 1}`, snapshot);
    setItems((current) => [created, ...current]);
    setSelected(created.id);
    setOpen(true);
  };
  const preview = async (item) => {
    if (!project) return;
    const detail = await api.getStageVersion(project.id, stage, item.id);
    setSelected(item.id);
    onRestore(detail.snapshot || {});
  };
  return <div className="stage-version-menu">
    <button className="outline" onClick={() => void save()}><Plus size={15}/>保存当前{label}版本</button>
    <button className="outline" onClick={() => setOpen((value) => !value)}><Archive size={15}/>{`历史${label}版本${items.length ? `（${items.length}）` : ""}`}</button>
    {open && <section className="stage-version-popover" role="dialog" aria-label={`${label}历史版本`}>
      <header><div><strong>{label}历史版本</strong><span>仅当前阶段，可滚动浏览</span></div><button aria-label="关闭历史版本" onClick={() => setOpen(false)}><X size={15}/></button></header>
      <div className="stage-version-list">{items.length ? items.map((item) => <button className={selected === item.id ? "active" : ""} key={item.id} onClick={() => void preview(item)}><b>V{item.version_no}</b><span>{item.name}<small>{new Date(item.created_at).toLocaleString("zh-CN")}</small></span>{selected === item.id && <Check size={15} weight="bold"/>}</button>) : <p>尚未保存版本。保存后会独立记录当前阶段，不影响其他阶段。</p>}</div>
    </section>}
  </div>;
}

function PatternCandidateStage({ notify, project, activeSourceAssetId, setActiveSourceAssetId, onNext, setActivePattern, boardLayout, setBoardLayout, customBoardLayouts = [], hasSavedBoardPlan = false }) {
  const [candidate, setCandidate] = useState("标准");
  const [layout, setLayout] = useState(boardLayout || "single");
  const [result, setResult] = useState(null);
  const [generationMode, setGenerationMode] = useState<"local" | "model_direct">("local");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [errorDetail, setErrorDetail] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [legacyCustomLayouts, setLegacyCustomLayouts] = useState([]);
  const candidates = [
    { id: "少色", colors: "最多 16 色", fit: "制作更省豆", detail: "色数上限 16；仅保留有识别价值的色块，不强制凑色", recommended: false },
    { id: "标准", colors: "最多 30 色", fit: "识别度与制作平衡", detail: "色数上限 30；保留稳定的结构色块，不强制凑色", recommended: true },
    { id: "丰富", colors: "最多 42 色", fit: "细节表现优先", detail: "色数上限 42；仅为可读的结构细节增加颜色，不强制凑色", recommended: false },
  ];
  const current = candidates.find((item) => item.id === candidate) || candidates[1];
  const mode = { "少色": "limited", "标准": "standard", "丰富": "rich" }[candidate];
  const layoutLabels = {
    single: "单板 52×52",
    double_horizontal: "双联横板 104×52",
    double_vertical: "双联竖板 52×104",
    quad: "四联方板 104×104",
    six_horizontal: "六联横板 156×104",
  };
  const selectableCustomLayouts = Array.from(new Set([
    ...customBoardLayouts,
    ...legacyCustomLayouts,
    ...(isCustomBoardLayout(layout) ? [layout] : []),
  ])).filter(isCustomBoardLayout);
  const customLayout = isCustomBoardLayout(layout);
  useEffect(() => {
    setLayout(boardLayout || "single");
    setConfirmed(false);
  }, [boardLayout]);
  useEffect(() => {
    if (!project) { setResult(null); return; }
    setLegacyCustomLayouts([]);
    let current = true;
    api.getLatestPattern(project.id).then((latest) => {
      if (!current) return;
      const formal = project.assets?.find((asset) => asset.id === activeSourceAssetId && asset.role === "confirmed_2d" && !asset.archived);
      if (formal && latest.source_asset_id !== formal.id) return;
      setResult(latest);
      // The board plan is the user's current decision.  A previously generated
      // pattern must not overwrite it when reopening this stage.
      const restoredLayout = hasSavedBoardPlan ? boardLayout : latest.board_layout || boardLayout || "single";
      if (isCustomBoardLayout(latest.board_layout)) {
        setLegacyCustomLayouts((items) => Array.from(new Set([...items, latest.board_layout])));
      }
      setLayout(restoredLayout);
      if (!hasSavedBoardPlan && isCustomBoardLayout(restoredLayout)) setBoardLayout(restoredLayout);
      setCandidate({limited:"少色",standard:"标准",rich:"丰富"}[latest.color_mode] || "标准");
      setConfirmed(true);
    }).catch(() => { if (current) setResult(null); });
    return () => { current = false; };
  }, [project?.id, activeSourceAssetId, boardLayout, hasSavedBoardPlan]);
  const generate = async () => {
    const source = project?.assets?.find((asset) => asset.id === activeSourceAssetId && asset.role === "confirmed_2d" && !asset.archived);
    if (!project || !source) { setError("未找到已确认的正式 2D，请返回 2D 页面确认候选。"); return; }
    setBusy(true); setError(""); setErrorDetail(""); setConfirmed(false);
    try {
      const generated = await api.generatePattern(project.id, source.id, layout, mode, generationMode);
      setResult(generated);
      notify(`${generationMode === "local" ? "本地引擎" : "大模型直出"}已按 MARD 色号真实生成`);
    } catch (cause) {
      const code = cause instanceof Error ? cause.message : "";
      const messages: Record<string, string> = {
        MODEL_NOT_IMAGE_GENERATION: "当前配置的是视觉理解模型，不能直接生成图纸成图。请改用支持图像生成的模型后重启应用。",
        MODEL_AUTH_FAILED: "API 密钥验证失败，请检查密钥与模型权限。",
        MODEL_QUOTA_EXHAUSTED: "模型额度不足或账户欠费，请在控制台检查余额与模型额度。",
        MODEL_NOT_AVAILABLE: "当前业务空间无权使用所填图像模型，请检查模型 ID 与开通权限。",
        MODEL_INPUT_INVALID: "正式 2D 不符合图像模型输入要求，请检查图片尺寸后重试。",
        MODEL_INPUT_SAFETY_REJECTED: "正式 2D 未通过内容安全检查，本次不会生成或保存本地图纸。",
        MODEL_RATE_LIMITED: "图像模型请求受到限流，请稍后重试。",
        MODEL_CONNECTION_FAILED: "无法连接 OpenAI API；请检查网络、代理/VPN、DNS、TLS 证书或防火墙后重试。",
        MODEL_TIMEOUT: "图像模型生成超时，本次没有保存图纸，可直接重试。",
        MODEL_GENERATION_FAILED: "图像模型未返回有效成图，本次没有保存图纸。",
      };
      setError(messages[code] || (code ? `生成失败：${code}` : "生成失败"));
      if (cause instanceof ApiError) {
        setErrorDetail([
          cause.providerCode && `OpenAI 错误码：${cause.providerCode}`,
          cause.providerMessage && `原因：${cause.providerMessage}`,
          cause.requestId && `Request ID：${cause.requestId}`,
          cause.diagnostics?.trace_id && `诊断编号：${cause.diagnostics.trace_id}`,
          cause.diagnostics?.elapsed_ms != null && `请求耗时：${(cause.diagnostics.elapsed_ms / 1000).toFixed(1)} 秒`,
          cause.diagnostics?.input && `图纸输入：${cause.diagnostics.input.original_size || "—"} → ${cause.diagnostics.input.prepared_size || "—"} · ${cause.diagnostics.input.format || "—"} · ${cause.diagnostics.input.bytes != null ? `${(cause.diagnostics.input.bytes / 1024 / 1024).toFixed(2)} MB` : "—"} · 透明像素 ${cause.diagnostics.input.transparent_pixel_ratio != null ? `${(cause.diagnostics.input.transparent_pixel_ratio * 100).toFixed(1)}%` : "—"}`,
          cause.diagnostics?.input?.sdk_attempts_max && `SDK 最多已尝试：${cause.diagnostics.input.sdk_attempts_max} 次`,
          cause.diagnostics?.connection_stage === "response_not_received_connection_closed" && "断开阶段：尚未收到 HTTP 响应，连接被对端或中间链路关闭",
          cause.diagnostics?.connection_stage === "tls_handshake_failed" && "断开阶段：TLS 证书/握手失败",
          cause.diagnostics?.connection_stage === "dns_resolution_failed" && "断开阶段：DNS 解析失败",
          cause.diagnostics?.transport?.proxy_configured && `检测到代理：${cause.diagnostics.transport.proxy_entries?.join("、")}`,
          cause.diagnostics?.exception_chain?.[1]?.message && `底层原因：${cause.diagnostics.exception_chain[1].message}`,
        ].filter(Boolean).join(" · "));
      }
    } finally { setBusy(false); }
  };
  const stats = result?.pattern.statistics;
  const palette = result?.pattern.palette || [];
  return <div className="pattern-candidate-stage">
    <aside className="pattern-options">
      <div className="stage-title"><span>04 / 图纸候选</span><h1>比较图纸方案</h1><p>三种颜色复杂度，使用图板阶段已确认的图板组合。</p></div><AssetPicker project={project} value={activeSourceAssetId} onChange={setActiveSourceAssetId} onlyFormal />
      <div className="option-head"><strong>候选方案</strong><button onClick={() => { setCandidate("标准"); setConfirmed(false); }}>采用推荐</button></div>
      <div className="pattern-candidate-list">{candidates.map((item) => <button key={item.id} className={candidate === item.id ? "active" : ""} onClick={() => { setCandidate(item.id); setConfirmed(false); }}><span className="candidate-swatch-stack">{swatches.slice(0, item.id === "少色" ? 4 : item.id === "标准" ? 6 : 8).map(([code,color]) => <i key={code} style={{background:color}} />)}</span><span><strong>{item.id}方案 {item.recommended && <em>推荐</em>}</strong><small>{item.colors}配色 · 豆数生成后计算</small><p>{item.fit}</p></span><b>{candidate === item.id && <Check size={13} weight="bold" />}</b></button>)}</div>
      <section className="candidate-diff-note"><ShareNetwork size={19} weight="fill" /><div><strong>图板规格（继承图板规划）</strong><p><select value={layout} onChange={(event) => { const next = event.target.value; setLayout(next); setBoardLayout(next); setConfirmed(false); }}><option value="single">{layoutLabels.single}</option><option value="double_horizontal">{layoutLabels.double_horizontal}</option><option value="double_vertical">{layoutLabels.double_vertical}</option><option value="quad">{layoutLabels.quad}</option><option value="six_horizontal">{layoutLabels.six_horizontal}</option>{selectableCustomLayouts.map((item) => <option value={item} key={item}>{customBoardLabel(item)}</option>)}</select></p><small>{customLayout ? "可直接选择当前素材已应用的自定义组合；生成图纸会按所选规格分板。" : selectableCustomLayouts.length ? "可从下拉框切换当前素材已应用的自定义组合。" : "如需自定义组合，请返回图板阶段设置并点击“应用组合”。"}</small></div></section>
      <section className="generation-mode-choice"><div><strong>图纸生成方式</strong><span>生成前选择，结果会记录在图纸数据中</span></div><label className={generationMode === "local" ? "active" : ""}><input type="radio" name="pattern-generation-mode" checked={generationMode === "local"} onChange={() => { setGenerationMode("local"); setConfirmed(false); }} /><b>本地引擎（v0.19.1 基线）</b><small>恢复为已验证的确定性落格算法：保留原图有效细节，并使用面部、轮廓与佩剑等细长结构保护；不再执行中间强制量化与纹理滤波。</small></label><label className={generationMode === "model_direct" ? "active" : ""}><input type="radio" name="pattern-generation-mode" checked={generationMode === "model_direct"} onChange={() => { setGenerationMode("model_direct"); setConfirmed(false); }} /><b>大模型直出</b><small>大模型仅依据正式 2D 生成图纸成图；程序只取格并匹配 MARD 色号。</small></label></section>
      <button className="primary" disabled={busy} onClick={generate}>{busy ? (generationMode === "model_direct" ? "大模型正在从正式 2D 直接生成图纸…" : "本地引擎正在生成图纸…") : result ? "按当前设置重新生成" : "生成当前真实图纸"}</button>
      {error && <p className="form-error">{error}</p>}
      {errorDetail && <p className="form-error-detail">{errorDetail}</p>}
    </aside>
    <section className="pattern-candidate-workspace">
      <header className="preview-head"><div><h2>{project?.name || "当前项目"} · {candidate}方案</h2><span>{result ? `${result.pattern.width} × ${result.pattern.height} 针 · MARD official-v1` : "等待生成真实网格"}</span></div><StageVersionMenu project={project} stage="pattern" label="图纸" snapshot={{ candidate, layout, generationMode, result }} onRestore={(saved) => { setCandidate(saved.candidate || "标准"); setLayout(saved.layout || "single"); setGenerationMode(saved.generationMode || "local"); setResult(saved.result || null); setConfirmed(Boolean(saved.result)); notify("已切换展示所选图纸历史版本"); }} /></header>
      <div className="pattern-candidate-canvas compare-仅图纸"><div className="candidate-board-wrap">{result ? <GeneratedPatternPreview result={result} /> : <div className="project-empty"><GridFour size={48}/><strong>尚未生成图纸</strong><span>选择图板和颜色档位后开始生成。</span></div>}</div></div>
      <footer className="pattern-candidate-footer"><div><ShieldCheck size={19} weight="fill" /><span><strong>{result ? "网格数据已保存" : "等待真实结果"}</strong><small>{result ? "每格已记录品牌、色号、显示色与所属图板" : "不会使用固定演示网格"}</small></span></div><div><button className="primary" disabled={!result} onClick={() => { setConfirmed(true); notify(`${candidate}方案已确认为正式图纸候选`); }}><Check size={17} weight="bold" />确认此方案</button></div></footer>
    </section>
    <aside className="pattern-candidate-inspector">
      <section className="config-card recommendation-card"><div className="config-title"><MagicWand size={20} weight="fill" /><div><strong>{stats?.semanticPlanning?.generationMode === "direct-model-image" ? "大模型已从正式 2D 直接生成图纸" : "本地引擎已按 v0.19.1 基线落格"}</strong><span>{stats?.semanticPlanning?.model || "确定性取格 · 关键细节保护 · MARD 映射"}</span></div></div><p>{stats?.semanticPlanning?.generationMode === "direct-model-image" ? "本次没有本地初稿参与生成或二次修正；程序只做取格、MARD 色号映射、统计与分板。" : "本次恢复为此前已验证的本地确定性算法，不使用会吞没细线与服装纹理的中间强制量化和 ModeFilter。"}</p>{stats?.semanticPlanning?.identityPriorities?.length > 0 && <p>重点保留：{stats.semanticPlanning.identityPriorities.join("、")}</p>}</section>
      <section className="config-card recommendation-card"><div className="config-title"><MagicWand size={20} weight="fill" /><div><strong>{stats ? (stats.qualityLevel === "good" ? "当前图纸表现良好" : stats.qualityLevel === "review" ? "当前图纸需要检查" : "当前图纸能力不足") : `${candidate}方案特点`}</strong><span>基于结构、颜色误差与可制作性计算</span></div></div><p>{stats?.qualityWarnings?.length ? stats.qualityWarnings.join("；") : current.detail}</p><div className="score-line"><span>结构质量评分</span><strong>{stats?.qualityScore == null ? "待生成" : `${stats.qualityScore}%`}</strong></div><i className="score-track"><b style={{width:`${stats?.qualityScore ?? 0}%`}} /></i>{stats?.recommendedMinimumBoard && <p>建议最低图板：{stats.recommendedMinimumBoard}</p>}</section>
      <section className="config-card"><div className="card-heading"><strong>方案数据</strong><span>真实计算结果</span></div><dl className="board-summary"><div><dt>品牌色库</dt><dd>MARD</dd></div><div><dt>颜色数量</dt><dd>{stats?.colorCount ?? "—"} 色</dd></div><div><dt>总豆数</dt><dd>{stats?.totalBeads?.toLocaleString() ?? "—"} 颗</dd></div><div><dt>成品尺寸</dt><dd>{stats ? `${stats.physicalWidthMm} × ${stats.physicalHeightMm} mm` : "—"}</dd></div></dl></section>
      <section className="config-card palette-detail-card"><div className="card-heading"><strong>颜色与色号</strong><span>{palette.length} 个真实色号</span></div><div className="candidate-palette">{palette.map((item) => <button key={item.code} onClick={() => notify(`已定位色号 ${item.code}`)}><i style={{background:item.value}} /><span>{item.code} · {item.count}</span></button>)}</div></section>
      <section className={`config-card candidate-confirm-card ${confirmed ? "ready" : ""}`}><div className="config-title">{confirmed ? <CheckCircle size={21} weight="fill" /> : <WarningCircle size={21} weight="fill" />}<div><strong>{confirmed ? `${candidate}方案已确认` : "请确认正式候选"}</strong><span>{confirmed ? "可进入编辑页逐项检查与修改" : "确认后仍可在编辑页调整色点"}</span></div></div><button className="primary" disabled={!confirmed} onClick={() => { setActivePattern(result); onNext(); notify("图纸候选已确认，进入编辑"); }}>进入图纸编辑 <ArrowRight size={17} /></button></section>
    </aside>
  </div>;
}

function TwoDStage({ notify, project, activeSourceAssetId, setActiveSourceAssetId, setProject, onNext }) {
  const [selectedAsset, setSelectedAsset] = useState(0);
  const [candidate, setCandidate] = useState("standard");
  const [composition, setComposition] = useState("全身");
  const [detail, setDetail] = useState("标准");
  const [candidateMode, setCandidateMode] = useState("single");
  const [compareSource, setCompareSource] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [candidates, setCandidates] = useState([]);
  const [version2DPreview, setVersion2DPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [errorDetail, setErrorDetail] = useState("");
  const [modelStatus, setModelStatus] = useState(null);
  const [modelStatusError, setModelStatusError] = useState("");
  const [maskEditor, setMaskEditor] = useState(false);
  const [maskMode, setMaskMode] = useState("keep");
  const [maskStrokes, setMaskStrokes] = useState([]);
  const [subjectMode, setSubjectMode] = useState("single");
  const [subjectBoxes, setSubjectBoxes] = useState([]);
  const [cropBox, setCropBox] = useState({ x: 0, y: 0, width: 1, height: 1 });
  const importInput = useRef(null);
  const [importing, setImporting] = useState(false);
  const originals = (project?.assets || []).filter((item) => item.role === "original" && !item.archived);
  const importedTwoD = (project?.assets || []).filter((item) => item.role === "confirmed_2d" && item.original_name.startsWith("[直导2D] ") && !item.archived);
  const assets = [...originals, ...importedTwoD];
  const source = assets.find((item) => item.id === activeSourceAssetId) || assets[selectedAsset];
  const isDirectImport = source?.role === "confirmed_2d";
  const sortedCandidates = [...candidates].sort((a,b) => new Date(b.asset.created_at) - new Date(a.asset.created_at));
  const newestAt = sortedCandidates[0] ? new Date(sortedCandidates[0].asset.created_at).getTime() : 0;
  const latestCandidates = sortedCandidates.filter((item) => newestAt - new Date(item.asset.created_at).getTime() < 10000);
  const selected = version2DPreview || latestCandidates.find((item) => item.variant === candidate) || latestCandidates[0];
  const refreshModelStatus = async () => {
    try {
      const status = await api.getImageModelStatus();
      setModelStatus(status);
      setModelStatusError("");
      return status;
    } catch {
      setModelStatus(null);
      setModelStatusError("暂时无法读取模型状态；点击生成时会自动重试。");
      return null;
    }
  };
  useEffect(() => {
    if (source?.id && source.id !== activeSourceAssetId) setActiveSourceAssetId(source.id);
  }, [source?.id]);
  useEffect(() => {
    void refreshModelStatus();
  }, []);
  useEffect(() => {
    if (!project || !source) return;
    if (source.role === "confirmed_2d") {
      setCandidates([{ asset: source, source_asset_id: source.id, variant: "standard", label: "已导入正式 2D", detail: "直接导入", recommended: true, quality: { confirmable: true, generationMode: "direct_import" } }]);
      setCandidate("standard"); setConfirmed(true);
      return;
    }
    const savedCrop = window.localStorage.getItem(`perler.crop.${project.id}.${source.id}`);
    if (savedCrop) setCropBox(JSON.parse(savedCrop));
    let current = true;
    void api.listTwoDCandidates(project.id, source.id).then((rows) => {
      if (!current) return;
      setCandidates(rows);
      const formal = rows.find((item) => item.asset.role === "confirmed_2d");
      setCandidate(formal?.variant || rows.find((item) => item.recommended)?.variant || rows[0]?.variant || "standard");
      setConfirmed(Boolean(formal));
    }).catch(() => { if (current) setCandidates([]); });
    return () => { current = false; };
  }, [project, source]);
  const importTwoD = async (files) => {
    if (!project || !files?.length) return;
    setImporting(true); setError(""); setErrorDetail("");
    try {
      await api.uploadConfirmedTwoD(project.id, Array.from(files));
      const loaded = await api.getProject(project.id);
      setProject(loaded);
      const imported = loaded.assets.filter((item) => item.role === "confirmed_2d" && !item.archived).at(-1);
      setActiveSourceAssetId(imported?.id || null);
      notify(`已导入 ${files.length} 张正式 2D，可直接进入图板规划`);
    } catch (cause) {
      const code = cause instanceof Error ? cause.message : "";
      setError(code === "PROJECT_ASSET_LIMIT_EXCEEDED" ? "每个项目最多保存 10 张正式 2D。" : "2D 图片导入失败，请检查格式、大小和本机服务。");
    } finally { setImporting(false); }
  };
  const generate = async () => {
    if (!project || !source) return setError("请先上传一张原始素材。");
    setBusy(true); setError(""); setErrorDetail("");
    try {
      // The initial status request can race the local API startup. Recheck on
      // every generation attempt so this button never silently stays disabled.
      const currentModelStatus = modelStatus?.configured ? modelStatus : await refreshModelStatus();
      if (!currentModelStatus?.configured) {
        setError(currentModelStatus?.provider === "dashscope"
          ? "尚未完整配置百炼 API Key 与 Workspace ID。请填写 services/api/.env 后重新启动应用。"
          : currentModelStatus
            ? "尚未配置 OPENAI_API_KEY。请填写 services/api/.env 后重新启动应用。"
            : "无法连接本地生成服务，暂时无法读取模型配置。请确认应用已启动后再次点击生成。"
        );
        return;
      }
      const rows = await api.generateModelTwoDCandidates(project.id, source.id, {
        crop: cropBox,
        subject_boxes: subjectBoxes,
        mask_strokes: maskStrokes,
        subject_mode: subjectMode,
        composition: composition === "全身" ? "full" : composition === "半身" ? "half" : "head",
        style: "clean polished 2D character illustration",
        outline: "automatic darker subject-color outline",
        candidate_mode: candidateMode,
        variant: detail === "简化" ? "simplified" : detail === "丰富" ? "rich" : "standard",
      });
      const loaded = await api.getProject(project.id); setProject(loaded);
      const historyRows = await api.listTwoDCandidates(project.id, source.id);
      setCandidates(historyRows); setVersion2DPreview(null); setCandidate(rows.find((item) => item.recommended)?.variant || rows[0]?.variant || "standard"); setConfirmed(false);
      notify(candidateMode === "single" ? `成品模型已生成 1 张${detail}方案` : "成品模型已生成简化、标准、丰富 3 张方案");
    } catch (cause) {
      const code = cause instanceof Error ? cause.message : "";
      const messages = {
        OPENAI_API_KEY_REQUIRED: "未检测到 OPENAI_API_KEY，请重新启动应用。",
        DASHSCOPE_API_KEY_REQUIRED: "未检测到 DASHSCOPE_API_KEY，请重新启动应用。",
        DASHSCOPE_WORKSPACE_ID_REQUIRED: "未检测到有效的 Workspace ID，请检查本机配置。",
        UNSUPPORTED_IMAGE_PROVIDER: "图像供应商配置无效，请选择 openai 或 dashscope。",
        MODEL_AUTH_FAILED: "API 密钥验证失败，请检查密钥、地域与业务空间权限。",
        MODEL_QUOTA_EXHAUSTED: "模型额度不足或账户欠费，请在控制台检查余额与模型额度。",
        MODEL_NOT_AVAILABLE: "当前账户无权使用所填模型，请检查模型 ID 与开通权限。",
        MODEL_INPUT_INVALID: "参考图不符合图像模型输入要求，请更换图片后重试。",
        MODEL_INPUT_SAFETY_REJECTED: "输入图片未通过内容安全检查，请更换素材；本次未生成候选，也不会覆盖已有资产。",
        MODEL_RATE_LIMITED: "模型请求受到限流，请稍后重试。",
        MODEL_CONNECTION_FAILED: "无法连接 OpenAI API；请检查网络、代理/VPN、DNS、TLS 证书或防火墙后重试。",
        MODEL_TIMEOUT: "模型生成超时，本次未产生候选，可直接重试。",
        MODEL_GENERATION_FAILED: "图像模型未返回有效结果，请查看下方具体原因。",
      };
      setError(messages[code] || "成品 2D 模型生成失败；原图与既有正式资产未被覆盖。");
      if (cause instanceof ApiError) {
        setErrorDetail([
          cause.providerCode && `${modelStatus?.provider === "dashscope" ? "百炼" : "OpenAI"} 错误码：${cause.providerCode}`,
          cause.providerMessage && `原因：${cause.providerMessage}`,
          cause.requestId && `Request ID：${cause.requestId}`,
          cause.diagnostics?.trace_id && `诊断编号：${cause.diagnostics.trace_id}`,
          cause.diagnostics?.elapsed_ms != null && `请求耗时：${(cause.diagnostics.elapsed_ms / 1000).toFixed(1)} 秒`,
          cause.diagnostics?.exception_chain?.[1]?.message && `底层原因：${cause.diagnostics.exception_chain[1].message}`,
        ].filter(Boolean).join(" · "));
      }
    }
    finally { setBusy(false); }
  };
  const confirm = async () => {
    if (!project || !selected) return;
    const isModelCandidate = selected.quality?.generationMode === "model_generated";
    if (!selected.quality?.confirmable && !isModelCandidate) {
      setError("当前结果仅为离线预处理参考稿，不能确认为正式 2D。");
      return;
    }
    setBusy(true); setError(""); setErrorDetail("");
    try {
      const confirmedAsset = await api.confirmTwoDCandidate(project.id, selected.asset.id);
      const loaded = await api.getProject(project.id); setProject(loaded);
      setActiveSourceAssetId(confirmedAsset.id);
      setConfirmed(true);
      notify(`${selected.label}已确认为正式 2D 形象，正在进入图板规划`);
      onNext();
    } catch (cause) {
      const code = cause instanceof Error ? cause.message : "";
      setError(code === "FINAL_2D_GENERATION_REQUIRED"
        ? "当前候选的背景或主体边缘仍需检查；系统未重新生成图片，也未消耗模型额度。"
        : `候选确认失败（${code || "未知错误"}），请重试。`);
      if (cause instanceof ApiError) {
        setErrorDetail([
          cause.providerMessage && `原因：${cause.providerMessage}`,
          cause.requestId && `Request ID：${cause.requestId}`,
        ].filter(Boolean).join(" · "));
      }
    }
    finally { setBusy(false); }
  };
  const markMask = (event) => {
    const box = event.currentTarget.getBoundingClientRect();
    setMaskStrokes((items) => [...items, {
      x: (event.clientX - box.left) / box.width,
      y: (event.clientY - box.top) / box.height,
      radius: 0.045,
      mode: maskMode,
    }]);
  };
  const quality = selected?.quality || {};
  const canAttemptConfirm = Boolean(
    selected
    && (quality.confirmable || quality.generationMode === "model_generated")
  );
  return <div className="twod-stage">
    <aside className="twod-queue">
      <div className="stage-title"><span>02 / 2D 形象</span><h1>确认形象候选</h1><p>可从原图生成，或直接导入已完成的 2D 形象。</p></div>
      <input ref={importInput} type="file" multiple accept="image/png,image/jpeg,image/webp" hidden onChange={(event) => { void importTwoD(event.target.files); event.target.value = ""; }} />
      <button className="outline direct-2d-import" disabled={importing} onClick={() => importInput.current?.click()}><UploadSimple size={16} />{importing ? "正在导入…" : "直接导入 2D"}</button>
      <div className="twod-progress"><div><strong>本批次</strong><span>{assets.filter((asset) => project.assets.some((item) => item.role === "confirmed_2d" && item.original_name.startsWith(asset.original_name.split(".")[0]))).length} / {assets.length} 已确认</span></div><i><b style={{width:`${assets.length ? (assets.filter((_, index) => index === selectedAsset && confirmed).length / assets.length) * 100 : 0}%`}} /></i></div>
      <div className="twod-assets">
        {assets.map((asset, index) => <button key={asset.id} className={source?.id === asset.id ? "active" : ""} onContextMenu={(event) => { event.preventDefault(); void api.archiveAsset(project.id, asset.id, true).then((loaded) => { setProject(loaded); setActiveSourceAssetId(null); notify("素材及其下游 2D 已归档"); }); }} onClick={() => { setSelectedAsset(index); setActiveSourceAssetId(asset.id); setConfirmed(false); }} title="右键归档">
          <img src={api.assetContentUrl(project.id, asset.id)} alt="" />
          <span><strong>{asset.original_name.replace("[直导2D] ", "")}</strong><small>{asset.role === "confirmed_2d" ? "已导入正式 2D" : selectedAsset === index && candidates.length ? `${candidates.length} 个候选` : "等待生成"}</small></span>
          {selectedAsset === index && confirmed ? <CheckCircle size={18} weight="fill" /> : <Circle size={18} />}
        </button>)}
        {!assets.length && <div className="batch-empty">请先上传原图，或直接导入已完成的 2D 图片。</div>}
      </div>
      <section className="twod-tip"><MagicWand size={19} weight="fill" /><div><strong>生成原则</strong><p>颜色可使用理想色；进入图纸阶段后再匹配真实品牌色号。</p></div></section>
    </aside>

    <section className="candidate-workspace">
      <header className="candidate-head">
        <div><h2>{source?.original_name || "当前素材"} · {isDirectImport ? "已导入正式 2D" : "最新 2D"} <em className="version-badge">v0.20.25</em></h2><span>{isDirectImport ? "已跳过原图分析与 2D 重绘，可直接进入图板规划" : `${composition}构图 · ${modelStatus?.provider === "dashscope" ? "阿里云百炼" : "OpenAI"} / ${modelStatus?.model || "图像模型"} · ${latestCandidates.length ? `最新一批 ${latestCandidates.length} 张` : `等待生成 ${candidateMode === "single" ? "1" : "3"} 张`}`}</span></div>
        <div className="candidate-head-actions"><label className="compare-switch"><input type="checkbox" checked={compareSource} onChange={() => setCompareSource(!compareSource)} /><i /><span>显示原图对照</span></label><StageVersionMenu project={project} stage="twod" label="2D" snapshot={{ candidateAssetId: selected?.asset.id, candidate, composition, detail }} onRestore={(saved) => { const item = candidates.find((entry) => entry.asset.id === saved.candidateAssetId); setVersion2DPreview(item || null); setCandidate(saved.candidate || "standard"); setComposition(saved.composition || "全身"); setDetail(saved.detail || "标准"); setConfirmed(Boolean(item?.asset.role === "confirmed_2d")); notify("已切换展示所选 2D 历史版本"); }} />{selected && <a className="outline" href={api.assetContentUrl(project.id, selected.asset.id)} download={selected.asset.original_name}><DownloadSimple size={16}/>导出当前 2D</a>}</div>
      </header>
      <div className={`candidate-body ${compareSource && !isDirectImport ? "" : "source-hidden"}`}>
        {compareSource && !isDirectImport && <article className="source-reference"><div className="card-label"><span>原始素材</span><button onClick={() => setMaskEditor(true)} title="修正主体蒙版"><Crop size={16} /></button></div><div className="reference-image">{source ? <img src={api.assetContentUrl(project.id, source.id)} alt="当前原始素材" /> : <ImageSquare size={48} />}</div><p>{maskStrokes.length || subjectBoxes.length ? `已应用 ${maskStrokes.length} 处蒙版修正、${subjectBoxes.length} 个主体框` : "可手动修正蒙版、主体与裁切。"}</p></article>}
        <div className={`candidate-list ${candidates.length === 1 ? "single" : ""}`}>
          {(version2DPreview ? [version2DPreview] : latestCandidates).map((item) => <article key={item.asset.id} className={`candidate-card ${selected?.asset.id === item.asset.id ? "active" : ""}`} onClick={() => { setVersion2DPreview(null); setCandidate(item.variant); setConfirmed(item.asset.role === "confirmed_2d"); }}>
            <div className="card-label"><div><b>{item.label}</b>{item.recommended && <em>推荐</em>}</div><span>{item.asset.role === "confirmed_2d" ? "正式 2D" : item.quality?.generationMode === "model_generated" ? "模型成品候选" : "预处理稿"}</span></div>
            <div className={`candidate-image ${item.variant}`}><img src={api.assetContentUrl(project.id, item.asset.id)} alt={`${item.label}预览`} /></div>
            <div className="candidate-meta"><div><strong>{item.detail}方案</strong><span>{item.variant === "simplified" ? "形状概括更多，适合小图板" : item.variant === "standard" ? "识别度、细节与可转化性平衡" : "保留更多服装和阴影细节"}</span></div><i>{selected?.asset.id === item.asset.id && <Check size={14} weight="bold" />}</i></div>
          </article>)}
          {!latestCandidates.length && <div className="project-empty"><MagicWand size={42}/><strong>尚未生成成品 2D</strong><span>{candidateMode === "single" ? `将只生成 1 张${detail}重绘方案，调用模型 1 次。` : "将生成简化、标准、丰富 3 张重绘方案，调用模型 3 次。"}</span></div>}
        </div>
      </div>
      {error && <section className="generation-error" role="alert"><WarningCircle size={20} weight="fill" /><div><strong>{error}</strong>{errorDetail && <span>{errorDetail}</span>}</div></section>}
      <footer className={`candidate-footer ${isDirectImport ? "direct-import-footer" : ""}`}>
        {isDirectImport ? <div className="direct-import-ready"><CheckCircle size={19} weight="fill" /><span><strong>已导入正式 2D</strong><small>无需重新生成，可直接进行图板规划。</small></span></div> : <div className="footer-generation-choice"><span>本次生成</span><div className="inline-count-choice">{[["single","1 张"],["all","3 张"]].map(([value,label]) => <button key={value} className={candidateMode === value ? "active" : ""} onClick={() => setCandidateMode(value)}>{label}</button>)}</div>{candidateMode === "single" && <select value={detail} onChange={(event) => setDetail(event.target.value)}><option>简化</option><option>标准</option><option>丰富</option></select>}</div>}
        <div>{isDirectImport ? <button className="primary" onClick={() => { onNext(); notify("已使用导入的正式 2D 进入图板规划"); }}><ArrowRight size={17} weight="bold" />进入图板规划</button> : <><button className="outline generate-action" disabled={busy || !source} onClick={() => void generate()}><ArrowClockwise size={16} />{busy ? "正在检查并生成，请勿关闭…" : candidates.length ? `重新生成 ${candidateMode === "single" ? `1 张${detail}` : "3 张"}` : `生成 ${candidateMode === "single" ? `1 张${detail}` : "3 张"}成品 2D`}</button><button className="primary" disabled={busy || !canAttemptConfirm} onClick={() => void confirm()}><Check size={17} weight="bold" />{busy ? "正在本地确认…" : "确认正式 2D"}</button></>}</div>
      </footer>
    </section>

    <aside className="twod-inspector">
      {!isDirectImport && <section className="twod-config">
        <div className="config-heading"><div><strong>生成设置</strong><span>调整后需重新生成候选</span></div><button onClick={() => { setComposition("全身"); setCandidateMode("single"); setDetail("标准"); notify("已恢复为单张标准推荐设置"); }}>恢复推荐</button></div>
        <label>生成数量<div className="segment candidate-count">{[["single","1 张"],["all","3 张"]].map(([value,label]) => <button key={value} className={candidateMode === value ? "active" : ""} onClick={() => setCandidateMode(value)}>{label}</button>)}</div></label>
        <p className="generation-cost-note">{candidateMode === "single" ? `仅生成${detail}方案，调用模型 1 次` : "固定生成简化、标准、丰富，调用模型 3 次"}</p>
        <label>构图类型<div className="segment">{["全身","半身","大头 Q 版"].map(v => <button key={v} className={composition === v ? "active" : ""} onClick={() => setComposition(v)}>{v}</button>)}</div></label>
        <label>主体关系<select value={subjectMode} onChange={(e) => { setSubjectMode(e.target.value); if (e.target.value === "single") setSubjectBoxes([]); }}><option value="single">单主体</option><option value="multiple">多主体 · 保持相对位置</option><option value="primary">多主体 · 突出主要主体</option></select></label>
        <button className="outline preprocess-button" disabled={!source} onClick={() => setMaskEditor(true)}><Crop size={16} />主体、蒙版与裁切</button>
        <label>形象风格<select defaultValue="清爽卡通"><option>清爽卡通</option><option>软萌 Q 版</option><option>扁平插画</option></select></label>
        <label>单张方案<div className={`segment ${candidateMode === "all" ? "disabled" : ""}`}>{["简化","标准","丰富"].map(v => <button key={v} disabled={candidateMode === "all"} className={detail === v ? "active" : ""} onClick={() => setDetail(v)}>{v}</button>)}</div></label>
        <label>轮廓处理<select defaultValue="自动选择深色轮廓"><option>自动选择深色轮廓</option><option>柔和无描边</option><option>强调轮廓</option></select></label>
        <label>背景处理<select defaultValue="透明背景"><option>透明背景</option><option>保留简化背景</option><option>纯色背景</option></select></label>
      </section>}
      <section className="twod-check">
        <strong>候选检查</strong>
        <div>{modelStatus?.configured ? <CheckCircle size={17} weight="fill" /> : <WarningCircle size={17} weight="fill" />}<span>生成模型连接</span><b>{modelStatus?.configured ? modelStatus.model : modelStatusError || "正在读取配置"}</b></div>
        <div>{quality.complexBackground ? <WarningCircle size={17} weight="fill" /> : <CheckCircle size={17} weight="fill" />}<span>复杂背景识别</span><b>{quality.score == null ? "待生成" : `${quality.score} 分`}</b></div>
        <div>{quality.touchesEdge ? <WarningCircle size={17} weight="fill" /> : <CheckCircle size={17} weight="fill" />}<span>主体边缘完整性</span><b>{quality.touchesEdge ? "提醒" : "通过"}</b></div>
        {quality.subjectMargins && <p className="quality-margins">有效主体留白：左 {quality.subjectMargins.left ?? "—"}px · 上 {quality.subjectMargins.top ?? "—"}px · 右 {quality.subjectMargins.right ?? "—"}px · 下 {quality.subjectMargins.bottom ?? "—"}px{quality.edgeSafetyMargin ? `（安全边距 ${quality.edgeSafetyMargin}px）` : ""}</p>}
        <div>{quality.complexityLevel === "complex" ? <WarningCircle size={17} weight="fill" /> : <CheckCircle size={17} weight="fill" />}<span>素材复杂度</span><b>{quality.complexityScore == null ? "待分析" : `${quality.complexityScore} · ${quality.complexityLevel === "complex" ? "复杂" : quality.complexityLevel === "medium" ? "中等" : "简单"}`}</b></div>
        <div><MagicWand size={17} weight="fill" /><span>推荐方案 / 图板</span><b>{quality.recommendedVariant ? `${quality.recommendedVariant === "simplified" ? "简化" : quality.recommendedVariant === "rich" ? "丰富" : "标准"} · ${quality.recommendedBoard}` : "待分析"}</b></div>
        <div><CheckCircle size={17} weight="fill" /><span>透明主体覆盖率</span><b>{quality.coverage == null ? "待生成" : `${Math.round(quality.coverage * 100)}%`}</b></div>
        <div>{quality.confirmable ? <CheckCircle size={17} weight="fill" /> : <WarningCircle size={17} weight="fill" />}<span>成品 2D 门槛</span><b>{quality.confirmable ? "可确认" : "未达到"}</b></div>
        {quality.warnings?.map((warning) => <p className="quality-warning" key={warning.code}>{warning.message}</p>)}
      </section>
      <section className={`twod-confirm ${confirmed ? "ready" : ""}`}>
        <div>{confirmed ? <CheckCircle size={22} weight="fill" /> : <WarningCircle size={22} weight="fill" />}<span><strong>{confirmed ? "2D 形象已确认" : "请先确认一个候选"}</strong><small>{confirmed ? "方案已保存，可进入图板规划" : "确认后会保存为正式中间资产"}</small></span></div>
        <button className="primary" disabled={!confirmed} onClick={() => { onNext(); notify("已进入图板规划"); }}>进入图板规划 <ArrowRight size={17} /></button>
      </section>
    </aside>
    {maskEditor && <div className="preprocess-modal"><section>
      <header><div><strong>主体、蒙版与裁切</strong><span>蓝色保留，红色移除；调整会在重新生成后生效。</span></div><button onClick={() => setMaskEditor(false)}><X size={18}/></button></header>
      <div className="preprocess-body">
        <div className="mask-canvas" onPointerDown={markMask}>
          {source && <img src={api.assetContentUrl(project.id, source.id)} alt="蒙版编辑原图" draggable={false}/>}
          {maskStrokes.map((point, index) => <i key={index} className={point.mode} style={{ left:`${point.x * 100}%`, top:`${point.y * 100}%` }}/>)}
          {subjectBoxes.map((box, index) => <b key={index} style={{ left:`${box.x * 100}%`, top:`${box.y * 100}%`, width:`${box.width * 100}%`, height:`${box.height * 100}%` }}>主体 {index + 1}</b>)}
        </div>
        <aside>
          <strong>蒙版画笔</strong><div className="segment"><button className={maskMode === "keep" ? "active" : ""} onClick={() => setMaskMode("keep")}>保留主体</button><button className={maskMode === "remove" ? "active" : ""} onClick={() => setMaskMode("remove")}>移除背景</button></div>
          <button className="outline" onClick={() => setMaskStrokes((items) => items.slice(0, -1))}>撤销上一笔</button>
          <strong>多主体</strong><button className="outline" disabled={subjectMode === "single"} onClick={() => setSubjectBoxes((items) => [...items, { x:0.12 + Math.min(items.length * 0.12, 0.3), y:0.12, width:0.42, height:0.76 }])}><Plus size={15}/>添加主体框</button>
          <button className="outline" disabled={!subjectBoxes.length} onClick={() => setSubjectBoxes([])}>清除主体框</button>
          <strong>裁切边界</strong>
          <label>左右裁切 <input type="range" min="0" max="20" value={Math.round(cropBox.x * 100)} onChange={(e) => { const value = Number(e.target.value) / 100; setCropBox({ x:value, y:cropBox.y, width:1-value*2, height:cropBox.height }); }}/></label>
          <label>上下裁切 <input type="range" min="0" max="20" value={Math.round(cropBox.y * 100)} onChange={(e) => { const value = Number(e.target.value) / 100; setCropBox({ x:cropBox.x, y:value, width:cropBox.width, height:1-value*2 }); }}/></label>
        </aside>
      </div>
      <footer><button className="outline" onClick={() => { setMaskStrokes([]); setSubjectBoxes([]); setCropBox({x:0,y:0,width:1,height:1}); }}>恢复自动识别</button><button className="primary" onClick={() => { setMaskEditor(false); setConfirmed(false); notify("预处理调整已保存，请重新生成候选"); }}>应用调整</button></footer>
    </section></div>}
  </div>;
}

function BoardStage({ notify, onNext, boardLayout, setBoardLayout, project, activeSourceAssetId, setActiveSourceAssetId }) {
  const layoutByApi = { single: "1×1", double_horizontal: "2×1", double_vertical: "1×2", quad: "2×2", six_horizontal: "3×2" };
  const apiByLayout = { "1×1": "single", "2×1": "double_horizontal", "1×2": "double_vertical", "2×2": "quad", "3×2": "six_horizontal" };
  const [layout, setLayout] = useState(layoutByApi[boardLayout] || "1×1");
  const [orientation, setOrientation] = useState("正方形");
  const [fit, setFit] = useState("完整显示");
  const [showSafe, setShowSafe] = useState(true);
  const [customOpen, setCustomOpen] = useState(boardLayout?.startsWith("custom_"));
  const customMatch = boardLayout?.match(/^custom_(\d+)x(\d+)$/);
  const [customCols, setCustomCols] = useState(Number(customMatch?.[1] || 2));
  const [customRows, setCustomRows] = useState(Number(customMatch?.[2] || 2));
  useEffect(() => {
    const restoredCustom = /^custom_(\d+)x(\d+)$/.exec(boardLayout || "");
    setCustomOpen(Boolean(restoredCustom));
    setLayout(restoredCustom ? `${restoredCustom[1]}×${restoredCustom[2]}` : layoutByApi[boardLayout] || "1×1");
    if (restoredCustom) { setCustomCols(Number(restoredCustom[1])); setCustomRows(Number(restoredCustom[2])); }
  }, [boardLayout]);
  const layouts = [
    { id: "1×1", label: "单板", pins: "52 × 52", size: "260 × 260 mm", count: 1, recommended: true },
    { id: "2×1", label: "双联横板", pins: "104 × 52", size: "520 × 260 mm", count: 2 },
    { id: "1×2", label: "双联竖板", pins: "52 × 104", size: "260 × 520 mm", count: 2 },
    { id: "2×2", label: "四联方板", pins: "104 × 104", size: "520 × 520 mm", count: 4 },
    { id: "3×2", label: "六联横板", pins: "156 × 104", size: "780 × 520 mm", count: 6 },
  ];
  const custom = { id: `${customCols}×${customRows}`, label: "自定义组合", pins: `${customCols * 52} × ${customRows * 52}`, size: `${customCols * 260} × ${customRows * 260} mm`, count: customCols * customRows };
  const current = customOpen ? custom : layouts.find((item) => item.id === layout) || layouts[0];
  const [cols, rows] = layout.split("×").map(Number);
  const previewAsset = project?.assets?.find((asset) => asset.id === activeSourceAssetId && asset.role === "confirmed_2d" && !asset.archived);
  const applyCustom = () => {
    if (customCols * customRows > 12) return notify("自定义组合最多 12 块标准板");
    const id = `${customCols}×${customRows}`;
    setLayout(id); setBoardLayout(`custom_${customCols}x${customRows}`); setCustomOpen(true);
    setOrientation(customCols > customRows ? "横版" : customCols < customRows ? "竖版" : "正方形");
    notify(`已应用 ${customCols}×${customRows} 自定义组合`);
  };
  return <div className="board-stage">
    <section className="board-options">
      <div className="stage-title"><span>03 / 图板规划</span><h1>选择实体图板</h1><p>按标准 5 mm 拼豆与 52 × 52 针方板规划。</p></div><AssetPicker project={project} value={activeSourceAssetId} onChange={setActiveSourceAssetId} onlyFormal />
      <div className="option-head"><strong>标准组合</strong><button onClick={() => { setCustomOpen(false); setLayout("1×1"); setBoardLayout("single"); setOrientation("正方形"); notify("已采用系统推荐的 52×52 单板"); }}>采用推荐</button></div>
      <div className="layout-list">{layouts.map((item) => <button key={item.id} className={!customOpen && layout === item.id ? "active" : ""} onClick={() => { setCustomOpen(false); setLayout(item.id); setBoardLayout(apiByLayout[item.id]); setOrientation(item.id === "2×1" || item.id === "3×2" ? "横版" : item.id === "1×2" ? "竖版" : "正方形"); }}>
        <span className={`layout-icon layout-${item.id.replace("×","-")}`}>{Array.from({ length: item.count }, (_, n) => <i key={n} />)}</span>
        <span><strong>{item.label}{item.recommended && <em>推荐</em>}</strong><small>{item.pins} 针 · {item.size}</small></span><b>{layout === item.id && <Check size={13} weight="bold" />}</b>
      </button>)}</div>
      <button className={`custom-board ${customOpen ? "active" : ""}`} onClick={() => setCustomOpen(!customOpen)}><Plus size={16} />自定义图板组合</button>
      {customOpen && <section className="custom-board-editor"><strong>设置标准板数量</strong><label>横向板数<input type="number" min="1" max="6" value={customCols} onChange={(event) => setCustomCols(Math.max(1, Math.min(6, Number(event.target.value))))}/></label><label>纵向板数<input type="number" min="1" max="6" value={customRows} onChange={(event) => setCustomRows(Math.max(1, Math.min(6, Number(event.target.value))))}/></label><small>每块均为 52×52 针，最多组合 12 块。</small><button className="primary" onClick={applyCustom}>应用组合</button></section>}
    </section>
    <section className="board-preview-panel">
      <div className="preview-head"><div><h2>主体占板预览</h2><span>已确认 2D 形象 · {project?.name || "当前项目"}</span></div><div className="preview-tools"><button className={fit === "完整显示" ? "active" : ""} onClick={() => setFit("完整显示")}><ArrowsOutLineHorizontal size={17} />完整显示</button><button className={fit === "铺满图板" ? "active" : ""} onClick={() => setFit("铺满图板")}><BoundingBox size={17} />铺满图板</button><StageVersionMenu project={project} stage="board" label="图板规划" snapshot={{ layout, boardLayout, orientation, fit, showSafe, customOpen, customCols, customRows }} onRestore={(saved) => { setLayout(saved.layout || "1×1"); setBoardLayout(saved.boardLayout || "single"); setOrientation(saved.orientation || "正方形"); setFit(saved.fit || "完整显示"); setShowSafe(saved.showSafe !== false); setCustomOpen(Boolean(saved.customOpen)); setCustomCols(saved.customCols || 2); setCustomRows(saved.customRows || 2); notify("已切换展示所选图板历史版本"); }} /></div></div>
      <div className="planning-canvas"><div className={`planning-board ${fit === "铺满图板" ? "fit-cover" : ""}`} style={{ "--board-ratio": `${cols} / ${rows}` }}>
        <div className="planning-grid" style={{ gridTemplateColumns: `repeat(${cols},1fr)`, gridTemplateRows: `repeat(${rows},1fr)` }}>{Array.from({ length: current.count }, (_, index) => { const row = Math.floor(index / cols), col = index % cols; return <div className="planning-board-cell" key={index}><span>{String.fromCharCode(65 + row)}{col + 1}</span></div>; })}</div>
        {showSafe && <div className="safe-area"><span>安全区域</span></div>}{project && previewAsset ? <img src={api.assetContentUrl(project.id, previewAsset.id)} alt={`${project.name}在标准豆板上的占板预览`} /> : <ImageSquare size={64}/>}
      </div></div>
      <div className="board-health"><span><ShieldCheck size={18} weight="fill" />主体完整，无超界</span><span><GridFour size={18} weight="fill" />拼接线避开关键五官</span><span><Ruler size={18} weight="fill" />预计成品 {current.size}</span></div>
    </section>
    <aside className="board-inspector">
      <section className="config-card summary-card"><div className="config-title"><SquaresFour size={20} weight="fill" /><div><strong>当前图板方案</strong><span>{current.label} · {current.count} 块标准板</span></div></div><dl className="board-summary"><div><dt>单板规格</dt><dd>52 × 52 针</dd></div><div><dt>总针数</dt><dd>{current.pins} 针</dd></div><div><dt>拼豆规格</dt><dd>5 mm</dd></div><div><dt>成品尺寸</dt><dd>{current.size}</dd></div></dl></section>
      <section className="config-card"><div className="card-heading"><strong>构图设置</strong><span>即时预览</span></div><label className="field-label">图板方向<select value={orientation} onChange={(e) => { setOrientation(e.target.value); notify(`图板方向已设为${e.target.value}`); }}><option>正方形</option><option>横版</option><option>竖版</option></select></label><label className="field-label">主体占比<select defaultValue="82% · 推荐"><option>72% · 留白更多</option><option>82% · 推荐</option><option>92% · 尽量铺满</option></select></label><label className="field-label">主体位置<select defaultValue="居中"><option>居中</option><option>略微上移</option><option>略微下移</option></select></label><label className="switch-line"><span><b>显示安全区域</b><small>边缘预留 2 针，降低掉豆风险</small></span><input type="checkbox" checked={showSafe} onChange={() => setShowSafe(!showSafe)} /><i /></label></section>
      <section className="config-card board-check-card"><div className="config-title"><ShieldCheck size={20} weight="fill" /><div><strong>图板检查通过</strong><span>未发现阻止继续的问题</span></div></div><ul><li><CheckCircle size={15} weight="fill" />主体未超出图板范围</li><li><CheckCircle size={15} weight="fill" />拼板方向与编号完整</li><li><CheckCircle size={15} weight="fill" />分板尺寸可直接用于图纸</li></ul><button className="primary" onClick={() => { onNext(); notify("图板方案已确认，进入图纸候选"); }}>确认图板并生成图纸 <ArrowRight size={17} /></button></section>
    </aside>
  </div>;
}

function MaterialStage({ notify, onNext, project, setProject, onProjectsChanged }) {
  const [selected, setSelected] = useState(0);
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef(null);
  const [removeBg, setRemoveBg] = useState(true);
  const [crop, setCrop] = useState("自动识别主体");
  const [subject, setSubject] = useState("单主体");
  const [previewMode, setPreviewMode] = useState("contain");
  const [cropActive, setCropActive] = useState(false);
  const [showArchived, setShowArchived] = useState(false);
  const [cropBox, setCropBox] = useState({ x: .08, y: .08, width: .84, height: .84 });
  const cropDrag = useRef(null);
  const items = project?.assets?.filter((asset) => asset.role === "original" && (showArchived ? asset.archived : !asset.archived)) ?? [];
  const item = items[selected] ?? null;
  useEffect(() => {
    if (!project || !item) return;
    const saved = window.localStorage.getItem(`perler.crop.${project.id}.${item.id}`);
    setCropBox(saved ? JSON.parse(saved) : { x:.08,y:.08,width:.84,height:.84 });
  }, [project?.id, item?.id]);
  useEffect(() => {
    if (!project || !item) return;
    window.localStorage.setItem(`perler.crop.${project.id}.${item.id}`, JSON.stringify(cropBox));
  }, [cropBox, project?.id, item?.id]);
  const moveCrop = (event) => {
    if (!cropDrag.current) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const px = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    const py = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));
    const min = .08, current = cropDrag.current.box;
    if (cropDrag.current.edge === "left") setCropBox({...current, x:Math.min(px,current.x+current.width-min), width:current.width+(current.x-px)});
    if (cropDrag.current.edge === "right") setCropBox({...current, width:Math.max(min,px-current.x)});
    if (cropDrag.current.edge === "top") setCropBox({...current, y:Math.min(py,current.y+current.height-min), height:current.height+(current.y-py)});
    if (cropDrag.current.edge === "bottom") setCropBox({...current, height:Math.max(min,py-current.y)});
  };
  const chooseFiles = () => fileInput.current?.click();
  const uploadFiles = async (files) => {
    if (!project) { notify("请先新建或打开一个项目"); return; }
    if (!files.length) return;
    setUploading(true);
    try {
      await api.uploadAssets(project.id, Array.from(files));
      const loaded = await api.getProject(project.id);
      setProject(loaded);
      setSelected(Math.max(0, loaded.assets.length - files.length));
      await onProjectsChanged();
      notify(`已保存 ${files.length} 张素材到本机`);
    } catch (cause) {
      const code = cause instanceof Error ? cause.message : "";
      notify(code === "PROJECT_ASSET_LIMIT_EXCEEDED" ? "每个项目最多保存 10 张素材" : "素材上传失败，请检查格式、大小和本机服务");
    } finally { setUploading(false); }
  };
  return <div className="material-stage">
    <section className="asset-queue">
      <div className="stage-title"><span>01 / 素材导入</span><h1>准备原始图片</h1><p>支持 PNG、JPG；单次可导入 2–10 张素材。</p></div>
      <input ref={fileInput} type="file" multiple accept="image/png,image/jpeg,image/webp" hidden onChange={(event) => void uploadFiles(event.target.files)} />
      <button className="upload-card" disabled={uploading} onClick={chooseFiles}><UploadSimple size={27} weight="bold" /><strong>{uploading ? "正在保存到本机…" : "拖放图片或点击上传"}</strong><span>JPG / PNG / WebP · 单张不超过 20 MB</span></button>
      <div className="queue-head"><strong>{showArchived ? "已归档素材" : "本批次素材"}</strong><span>{items.length} / 10</span></div>
      <div className="asset-list">
        {items.map((asset, index) => <button key={asset.id} className={`asset-row ${selected === index ? "active" : ""}`} onContextMenu={(event) => { event.preventDefault(); void api.archiveAsset(project.id, asset.id, !asset.archived).then(async (loaded) => { setProject(loaded); await onProjectsChanged(); notify(asset.archived ? "素材已恢复" : "素材已归档"); }); }} onClick={() => setSelected(index)} title="右键归档或恢复">
          <img src={api.assetContentUrl(project.id, asset.id)} alt="" />
          <span className="asset-meta"><strong>{asset.original_name}</strong><small>{(asset.file_size / 1024 / 1024).toFixed(2)} MB</small><em className="done">已保存</em></span>
        </button>)}
      </div>
      <button className="text-add" onClick={() => setShowArchived(!showArchived)}><Archive size={16} />{showArchived ? "返回当前素材" : "查看已归档素材"}</button><button className="text-add" disabled={showArchived || uploading || items.length >= 10} onClick={chooseFiles}><Plus size={16} />继续添加素材</button>
    </section>
    <section className="asset-preview">
      <div className="preview-head"><div><h2>{item?.original_name ?? "等待添加素材"}</h2><span>{item ? `${item.mime_type} · ${(item.file_size / 1024 / 1024).toFixed(2)} MB` : "素材会保存在本机项目目录"}</span></div><div className="preview-tools"><button className={previewMode === "contain" ? "active" : ""} onClick={() => { setPreviewMode("contain"); setCropActive(false); }}><MagnifyingGlass size={17} />适应</button><button className={cropActive ? "active" : ""} disabled={!item} onClick={() => { setCropActive(!cropActive); setPreviewMode("cover"); setCrop("手动裁切"); }}><Crop size={17} />裁切</button></div></div>
      <div className="image-stage">
        {item ? <div className={`source-frame preview-${previewMode} ${cropActive ? "crop-active" : ""}`} onPointerMove={moveCrop} onPointerUp={() => { cropDrag.current=null; notify("裁切范围已保存"); }}><img src={api.assetContentUrl(project.id, item.id)} alt="当前原始素材预览" />{cropActive && <div className="crop-selection" style={{left:`${cropBox.x*100}%`,top:`${cropBox.y*100}%`,width:`${cropBox.width*100}%`,height:`${cropBox.height*100}%`}}>{["left","right","top","bottom"].map((edge)=><button key={edge} className={`crop-edge ${edge}`} aria-label={`拖动${edge}裁切线`} onPointerDown={(event)=>{event.currentTarget.setPointerCapture(event.pointerId);cropDrag.current={edge,box:cropBox};}} />)}<span className="corner tl" /><span className="corner tr" /><span className="corner bl" /><span className="corner br" /></div>}</div> :
          <div className="source-placeholder"><ImageSquare size={80} /><strong>尚未添加素材</strong><span>从左侧选择 1–10 张图片</span></div>}
      </div>
      <div className="asset-health"><span><CheckCircle size={18} weight="fill" />清晰度良好</span><span><CheckCircle size={18} weight="fill" />主体完整</span><span><CheckCircle size={18} weight="fill" />无版权水印</span></div>
    </section>
    <aside className="material-inspector">
      <section className="config-card">
        <div className="config-title"><MagicWand size={20} weight="fill" /><div><strong>素材识别</strong><span>系统已完成初步分析</span></div></div>
        <dl className="recognition"><div><dt>当前素材</dt><dd>{item?.original_name || "未选择"}</dd></div><div><dt>主体数量</dt><dd>{subject.startsWith("多主体") ? "多个主体" : "1 个主要主体"}</dd></div><div><dt>预览方式</dt><dd>{previewMode === "contain" ? "保持原比例完整显示" : "裁切预览"}</dd></div><div><dt>推荐构图</dt><dd>完整主体</dd></div></dl>
      </section>
      <section className="config-card">
        <div className="card-heading"><strong>基础预处理</strong><span>不会覆盖原图</span></div>
        <label className="switch-line"><span><b>自动去除背景</b><small>生成透明底预处理图</small></span><input type="checkbox" checked={removeBg} onChange={() => setRemoveBg(!removeBg)} /><i /></label>
        <label className="field-label">裁切方式<select value={crop} onChange={(e) => { setCrop(e.target.value); setCropActive(e.target.value === "手动裁切"); }}><option>自动识别主体</option><option>保留原图比例</option><option>手动裁切</option></select></label>
        {cropActive && <button className="outline crop-reset" onClick={()=>setCropBox({x:0,y:0,width:1,height:1})}>恢复完整画面</button>}
        <label className="field-label">主体关系<select value={subject} onChange={(e) => setSubject(e.target.value)}><option>单主体</option><option>多主体 · 保持相对位置</option><option>多主体 · 突出主要主体</option></select></label>
        <label className="field-label">项目归属<select value={project?.name || ""} disabled><option>{project?.name || "未打开项目"}</option></select></label>
      </section>
      <section className="config-card batch-summary">
        <div className="config-title"><Stack size={20} weight="fill" /><div><strong>批次准备情况</strong><span>{items.length ? `${items.length} 张已保存到本机` : "请至少添加 1 张素材"}</span></div></div>
        <div className="progress"><i style={{width: items.length ? "100%" : "0%"}} /></div>
        <button className="primary" disabled={!items.length || uploading} onClick={() => { onNext(); notify("素材已确认，进入 2D 生成"); }}>确认当前素材并进入 2D <ArrowRight size={17} /></button>
      </section>
    </aside>
  </div>;
}

function Panel({ title, open, setOpen, children, className = "" }) {
  return <section className={`panel ${className}`}>
    <button className="panel-title" onClick={() => setOpen(!open)}><span>{title}</span>{open ? <CaretUp size={15} /> : <CaretDown size={15} />}</button>
    {open && <div className="panel-content">{children}</div>}
  </section>;
}
