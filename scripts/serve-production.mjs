import { createReadStream, existsSync, readFileSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { basename, extname, normalize, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const projectRoot = resolve(fileURLToPath(new URL('..', import.meta.url)));
const clientRoot = resolve(projectRoot, 'dist/client');
const worker = (await import(resolve(projectRoot, 'dist/server/index.js'))).default;
const host = process.env.PERLER_HOST ?? '127.0.0.1';
const port = Number(process.env.PERLER_PORT ?? 3000);

const mimeTypes = {
  '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.woff2': 'font/woff2',
};

function localAsset(pathname) {
  const relative = normalize(pathname.replace(/^\/+/, ''));
  if (!relative || relative.startsWith('..')) return null;
  const absolute = resolve(clientRoot, relative);
  if (!absolute.startsWith(`${clientRoot}/`) || !existsSync(absolute) || !statSync(absolute).isFile()) return null;
  return absolute;
}

function sendFile(response, file) {
  response.writeHead(200, {
    'Content-Type': mimeTypes[extname(file).toLowerCase()] ?? 'application/octet-stream',
    'Cache-Control': '/assets/'.includes(`/assets/${basename(file)}`) ? 'public, max-age=31536000, immutable' : 'no-cache',
  });
  createReadStream(file).pipe(response);
}

const assets = {
  async fetch(request) {
    const file = localAsset(new URL(request.url).pathname);
    if (!file) return new Response('Not Found', { status: 404 });
    return new Response(readFileSync(file), { status: 200 });
  },
};

createServer(async (request, response) => {
  try {
    const origin = `http://${host}:${port}`;
    const url = new URL(request.url ?? '/', origin);
    const file = localAsset(url.pathname);
    if (file) return sendFile(response, file);

    const body = ['GET', 'HEAD'].includes(request.method ?? 'GET') ? undefined : request;
    const webRequest = new Request(url, { method: request.method, headers: request.headers, body, duplex: body ? 'half' : undefined });
    const result = await worker.fetch(webRequest, { ASSETS: assets });
    response.writeHead(result.status, Object.fromEntries(result.headers));
    if (!result.body || request.method === 'HEAD') return response.end();
    const reader = result.body.getReader();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      response.write(value);
    }
    response.end();
  } catch (error) {
    console.error(error);
    response.writeHead(500, { 'Content-Type': 'text/plain; charset=utf-8' });
    response.end('前端启动失败，请将此窗口截图发送给开发人员。');
  }
}).listen(port, host, () => {
  console.log(`拼豆工作台前端已启动：http://${host}:${port}`);
});
