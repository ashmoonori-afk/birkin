import { createHash } from "node:crypto";
let input = "";
for await (const chunk of process.stdin) input += chunk;
const request = JSON.parse(input);
process.stdout.write(JSON.stringify({ok: true, request_id: request.request_id, adapter_sha256: createHash("sha256").update(input).digest("hex")}));
