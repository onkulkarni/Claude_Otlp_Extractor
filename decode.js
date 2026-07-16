const path = require('path');
const protobuf = require('protobufjs');

const PROTO_ROOT = path.join(__dirname, 'proto');

const SERVICE_FILES = [
  'opentelemetry/proto/collector/logs/v1/logs_service.proto',
  'opentelemetry/proto/collector/metrics/v1/metrics_service.proto',
  'opentelemetry/proto/collector/trace/v1/trace_service.proto',
];

const TOJSON_OPTIONS = { longs: String, enums: String, bytes: String, defaults: true };

let messageTypes = null;

async function load() {
  const root = new protobuf.Root();
  // All imports in the vendored .proto files are written relative to the
  // opentelemetry-proto repo root (e.g. "opentelemetry/proto/logs/v1/logs.proto"),
  // regardless of which file does the importing — so resolving every import
  // against our vendored proto/ dir, ignoring origin, is correct here.
  root.resolvePath = (origin, target) => path.join(PROTO_ROOT, target);

  await root.load(SERVICE_FILES);

  messageTypes = {
    logs: root.lookupType('opentelemetry.proto.collector.logs.v1.ExportLogsServiceRequest'),
    metrics: root.lookupType('opentelemetry.proto.collector.metrics.v1.ExportMetricsServiceRequest'),
    traces: root.lookupType('opentelemetry.proto.collector.trace.v1.ExportTraceServiceRequest'),
  };
}

function decode(signal, buffer) {
  if (!messageTypes) {
    throw new Error('decode.load() must be awaited before decode()');
  }
  const type = messageTypes[signal];
  const message = type.decode(buffer);
  return type.toObject(message, TOJSON_OPTIONS);
}

module.exports = { load, decode };
