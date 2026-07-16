const http = require('http');
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const decode = require('./decode');

const PORT = 4318;
const RECEIVED_DIR = path.join(__dirname, 'received');

const ROUTES = {
  '/v1/metrics': 'metrics',
  '/v1/logs': 'logs',
  '/v1/traces': 'traces',
};

let counter = 0;

function timestampForFilename() {
  return new Date().toISOString().replace(/:/g, '-');
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', (chunk) => chunks.push(chunk));
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

function maybeGunzip(buffer, req) {
  if (req.headers['content-encoding'] === 'gzip') {
    return zlib.gunzipSync(buffer);
  }
  return buffer;
}

function writeJson(signal, seq, name, data) {
  const filePath = path.join(RECEIVED_DIR, signal, `${name}.json`);
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2));
  console.log(`[${seq}] wrote ${filePath}`);
}

function writeRawFallback(signal, name, buffer, err) {
  const filePath = path.join(RECEIVED_DIR, signal, `${name}.raw.bin`);
  fs.writeFileSync(filePath, buffer);
  console.error(`decode failed for ${signal}, wrote raw bytes to ${filePath}:`, err.message);
}

function respondEmptyProtobufOk(res) {
  res.writeHead(200, { 'Content-Type': 'application/x-protobuf' });
  res.end();
}

async function handleExport(req, res, signal) {
  const seq = ++counter;
  const rawBody = await readBody(req);
  let body;
  try {
    body = maybeGunzip(rawBody, req);
  } catch (err) {
    console.error(`gunzip failed for ${signal} request #${seq}:`, err.message);
    res.writeHead(400);
    res.end();
    return;
  }

  const name = `${timestampForFilename()}_${signal}_${String(seq).padStart(6, '0')}`;

  try {
    const decoded = decode.decode(signal, body);
    writeJson(signal, seq, name, decoded);
  } catch (err) {
    writeRawFallback(signal, name, body, err);
  }

  respondEmptyProtobufOk(res);
}

async function main() {
  await decode.load();

  const server = http.createServer((req, res) => {
    const signal = req.method === 'POST' ? ROUTES[req.url] : undefined;
    if (!signal) {
      res.writeHead(404);
      res.end();
      return;
    }
    handleExport(req, res, signal).catch((err) => {
      console.error(`unhandled error processing ${signal} request:`, err);
      res.writeHead(500);
      res.end();
    });
  });

  server.listen(PORT, () => {
    console.log(`OTLP receiver listening on http://localhost:${PORT}`);
    console.log(`  POST /v1/metrics, /v1/logs, /v1/traces -> ${RECEIVED_DIR}`);
  });
}

main();
