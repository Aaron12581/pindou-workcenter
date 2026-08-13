import { app, BrowserWindow, dialog, Menu } from "electron";
import { accessSync, constants, cpSync, existsSync, mkdirSync } from "node:fs";
import { createServer } from "node:net";
import { basename, dirname, join } from "node:path";
import { spawn } from "node:child_process";

const APP_NAME = "拼豆图纸工作台";
const API_PORT = 18080;
const CHILDREN = [];
let mainWindow;

app.setName(APP_NAME);

function bundled(relativePath) {
  return app.isPackaged
    ? join(process.resourcesPath, relativePath)
    : join(app.getAppPath(), "runtime", relativePath);
}

function dataRoot() {
  return join(app.getPath("userData"), "data");
}

function settingsRoot() {
  return join(app.getPath("userData"), "settings");
}

function hasExistingData() {
  return existsSync(join(dataRoot(), "perler.db"));
}

function copyLegacyData(source) {
  if (basename(source) !== ".data") {
    throw new Error("请选择旧项目 services/api/.data 文件夹。");
  }
  mkdirSync(dirname(dataRoot()), { recursive: true });
  cpSync(source, dataRoot(), { recursive: true, force: false, errorOnExist: false });
  const legacyEnv = join(dirname(source), ".env");
  if (existsSync(legacyEnv)) {
    mkdirSync(settingsRoot(), { recursive: true });
    cpSync(legacyEnv, join(settingsRoot(), ".env"), { force: false, errorOnExist: false });
  }
}

async function chooseLegacyData() {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: "迁移旧版拼豆项目数据",
    message: "请选择旧项目中的 services/api/.data 文件夹",
    properties: ["openDirectory"],
  });
  if (result.canceled || !result.filePaths[0]) return false;
  try {
    copyLegacyData(result.filePaths[0]);
    await dialog.showMessageBox(mainWindow, {
      type: "info",
      title: "迁移完成",
      message: "旧版项目数据已复制到新应用。原文件未被修改。",
    });
    return true;
  } catch (error) {
    await dialog.showMessageBox(mainWindow, {
      type: "error",
      title: "无法迁移数据",
      message: error instanceof Error ? error.message : "请选择正确的 .data 文件夹后重试。",
    });
    return false;
  }
}

async function migrateOnFirstLaunch() {
  if (hasExistingData()) return;
  const answer = await dialog.showMessageBox({
    type: "question",
    title: "迁移旧项目数据",
    message: "是否导入旧版拼豆工作台的数据？",
    detail: "请选择旧项目目录中的 services/api/.data 文件夹。选择“稍后”也不会影响新建项目。",
    buttons: ["选择旧数据文件夹", "稍后"],
    defaultId: 0,
  });
  if (answer.response === 0) await chooseLegacyData();
}

function reservePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : undefined;
      server.close((error) => error ? reject(error) : resolve(port));
    });
  });
}

function spawnChild(command, args, env) {
  accessSync(command, constants.X_OK);
  const child = spawn(command, args, { env, stdio: "ignore", windowsHide: true });
  CHILDREN.push(child);
  return child;
}

async function waitFor(url, label) {
  let lastError;
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`${label}启动超时${lastError ? `：${lastError.message}` : ""}`);
}

async function startServices() {
  mkdirSync(dataRoot(), { recursive: true });
  mkdirSync(settingsRoot(), { recursive: true });
  const frontendPort = await reservePort();
  const sharedEnv = {
    ...process.env,
    PERLER_DATA_ROOT: dataRoot(),
    PERLER_ENV_FILE: join(settingsRoot(), ".env"),
    PERLER_DESKTOP_MODE: "true",
    PERLER_HOST: "127.0.0.1",
  };

  spawnChild(bundled("backend/perler-api"), [], { ...sharedEnv, PERLER_PORT: String(API_PORT) });
  await waitFor(`http://127.0.0.1:${API_PORT}/health`, "图纸服务");

  spawnChild(process.execPath, [bundled("frontend/scripts/serve-production.mjs")], {
    ...sharedEnv,
    ELECTRON_RUN_AS_NODE: "1",
    PERLER_PORT: String(frontendPort),
  });
  await waitFor(`http://127.0.0.1:${frontendPort}/`, "应用界面");
  return `http://127.0.0.1:${frontendPort}/?version=0.21.0`;
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1480,
    height: 940,
    minWidth: 1180,
    minHeight: 740,
    title: APP_NAME,
    show: false,
    webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false },
  });
  mainWindow.once("ready-to-show", () => mainWindow.show());
  return mainWindow;
}

function installMenu() {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    {
      label: APP_NAME,
      submenu: [
        { label: "迁移旧版项目数据…", click: () => chooseLegacyData() },
        { type: "separator" },
        { role: "quit", label: "退出拼豆图纸工作台" },
      ],
    },
    { role: "editMenu", label: "编辑" },
    { role: "windowMenu", label: "窗口" },
  ]));
}

app.whenReady().then(async () => {
  installMenu();
  createWindow();
  await migrateOnFirstLaunch();
  try {
    await mainWindow.loadURL(await startServices());
  } catch (error) {
    await dialog.showMessageBox(mainWindow, {
      type: "error",
      title: "拼豆图纸工作台无法启动",
      message: "本地服务未能正常启动。",
      detail: error instanceof Error ? error.message : String(error),
    });
    app.quit();
  }
});

app.on("window-all-closed", () => app.quit());
app.on("before-quit", () => {
  for (const child of CHILDREN) child.kill();
});
