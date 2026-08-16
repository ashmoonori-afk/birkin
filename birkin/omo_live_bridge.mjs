import { randomBytes, timingSafeEqual } from "node:crypto";
import { mkdir, open, rename, unlink } from "node:fs/promises";
import { createServer } from "node:net";
import { dirname, join } from "node:path";

const PROTOCOL = 1;
const HOST = "127.0.0.1";
const MAX_REQUEST_BYTES = 65_536;
const MAX_MESSAGE_CHARS = 32_768;
const MAX_RECEIPTS = 512;
const SESSION_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;

function qaLog(event, payload) {
  if (process.env.BIRKIN_OMO_BRIDGE_QA !== "1") return;
  process.stderr.write(
    `BIRKIN_OMO_BRIDGE_QA ${JSON.stringify({ event, ...payload })}\n`,
  );
}

function safeTokenEquals(expected, received) {
  if (typeof received !== "string") return false;
  const left = Buffer.from(expected);
  const right = Buffer.from(received);
  return left.length === right.length && timingSafeEqual(left, right);
}

function requestSignature(request) {
  return JSON.stringify([
    request.session_id,
    request.operation,
    request.message ?? null,
  ]);
}

async function writePrivateJson(path, value) {
  await mkdir(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.${process.pid}.${randomBytes(8).toString("hex")}.tmp`;
  const handle = await open(temporary, "wx", 0o600);
  try {
    await handle.writeFile(`${JSON.stringify(value)}\n`, "utf8");
    await handle.sync();
  } finally {
    await handle.close();
  }
  await rename(temporary, path);
}

function errorResponse(sessionId, requestId, error) {
  return {
    protocol: PROTOCOL,
    session_id: sessionId,
    request_id: requestId,
    ok: false,
    error,
  };
}

function successResponse(sessionId, requestId, payload = {}) {
  return {
    protocol: PROTOCOL,
    session_id: sessionId,
    request_id: requestId,
    ok: true,
    ...payload,
  };
}

export default function birkinOmoLiveBridge(pi) {
  let active = null;
  let deliveryCount = 0;
  const receipts = new Map();

  async function stop() {
    const selected = active;
    active = null;
    if (selected === null) return;
    await unlink(selected.registrationPath).catch(() => {});
    await new Promise((resolve) => selected.server.close(() => resolve()));
    qaLog("stopped", { session_id: selected.sessionId });
  }

  function remember(requestId, signature, response) {
    receipts.set(requestId, { signature, response });
    if (receipts.size > MAX_RECEIPTS) {
      const oldest = receipts.keys().next().value;
      receipts.delete(oldest);
    }
  }

  function handleRequest(selected, request) {
    const requestId =
      typeof request.request_id === "string" ? request.request_id : "";
    if (request.protocol !== PROTOCOL) {
      return errorResponse(selected.sessionId, requestId, "protocol mismatch");
    }
    if (!safeTokenEquals(selected.token, request.token)) {
      return errorResponse(selected.sessionId, requestId, "unauthorized");
    }
    if (request.session_id !== selected.sessionId) {
      return errorResponse(selected.sessionId, requestId, "session mismatch");
    }
    if (!SESSION_ID_PATTERN.test(requestId)) {
      return errorResponse(selected.sessionId, requestId, "invalid request id");
    }

    const signature = requestSignature(request);
    const prior = receipts.get(requestId);
    if (prior !== undefined) {
      if (prior.signature !== signature) {
        return errorResponse(
          selected.sessionId,
          requestId,
          "request id conflict",
        );
      }
      return { ...prior.response, replayed: true };
    }

    let response;
    if (request.operation === "state") {
      response = successResponse(selected.sessionId, requestId, {
        is_streaming: !selected.context.isIdle(),
        delivery_count: deliveryCount,
      });
    } else if (request.operation === "abort") {
      selected.context.abort("user");
      response = successResponse(selected.sessionId, requestId, {
        accepted: true,
      });
    } else if (
      request.operation === "prompt" ||
      request.operation === "steer"
    ) {
      if (
        typeof request.message !== "string" ||
        request.message.length === 0 ||
        request.message.length > MAX_MESSAGE_CHARS
      ) {
        return errorResponse(
          selected.sessionId,
          requestId,
          "invalid message",
        );
      }
      const deliverAs =
        request.operation === "steer" || !selected.context.isIdle()
          ? { deliverAs: "steer" }
          : undefined;
      pi.sendUserMessage(request.message, deliverAs);
      deliveryCount += 1;
      response = successResponse(selected.sessionId, requestId, {
        accepted: true,
      });
      qaLog("delivery", {
        session_id: selected.sessionId,
        request_id: requestId,
        operation: request.operation,
        message: request.message,
        delivery_count: deliveryCount,
      });
    } else if (request.operation === "last") {
      response = successResponse(selected.sessionId, requestId, { text: null });
    } else {
      return errorResponse(
        selected.sessionId,
        requestId,
        "unsupported operation",
      );
    }

    remember(requestId, signature, response);
    return response;
  }

  function serveSocket(selected, socket) {
    let buffered = Buffer.alloc(0);
    socket.setTimeout(2_000, () => socket.destroy());
    socket.on("data", (chunk) => {
      buffered = Buffer.concat([buffered, chunk]);
      if (buffered.length > MAX_REQUEST_BYTES) {
        socket.end(
          `${JSON.stringify(errorResponse(selected.sessionId, "", "request too large"))}\n`,
        );
        return;
      }
      const newline = buffered.indexOf(10);
      if (newline === -1) return;
      socket.pause();
      let response;
      try {
        const request = JSON.parse(buffered.subarray(0, newline).toString("utf8"));
        response = handleRequest(selected, request);
      } catch {
        response = errorResponse(selected.sessionId, "", "invalid json");
      }
      socket.end(`${JSON.stringify(response)}\n`);
    });
  }

  async function start(context) {
    await stop();
    receipts.clear();
    deliveryCount = 0;
    const sessionId = context.sessionManager.getSessionId();
    if (!SESSION_ID_PATTERN.test(sessionId)) return;
    const token = randomBytes(32).toString("hex");
    const registryRoot =
      process.env.BIRKIN_OMO_LIVE_DIR ??
      join(context.agentDir, "birkin", "live-sessions");
    const nonce = randomBytes(8).toString("hex");
    const registrationPath = join(
      registryRoot,
      `${sessionId}.${process.pid}.${nonce}.json`,
    );
    const server = createServer();
    const selected = {
      context,
      registrationPath,
      server,
      sessionId,
      token,
    };
    server.on("connection", (socket) => serveSocket(selected, socket));
    await new Promise((resolve, reject) => {
      server.once("error", reject);
      server.listen(0, HOST, () => {
        server.removeListener("error", reject);
        resolve();
      });
    });
    server.unref();
    const address = server.address();
    active = selected;
    if (address === null || typeof address === "string") {
      await stop();
      return;
    }
    try {
      await writePrivateJson(registrationPath, {
        protocol: PROTOCOL,
        session_id: sessionId,
        host: HOST,
        port: address.port,
        token,
        pid: process.pid,
        session_file: context.sessionManager.getSessionFile() ?? null,
        cwd: context.sessionManager.getCwd(),
      });
      qaLog("ready", {
        session_id: sessionId,
        registration_path: registrationPath,
      });
    } catch (error) {
      await stop();
      throw error;
    }
  }

  pi.on("session_start", async (_event, context) => start(context));
  pi.on("session_shutdown", async () => stop());
}
