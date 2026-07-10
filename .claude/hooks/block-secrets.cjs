#!/usr/bin/env node
// SPDX-FileCopyrightText: 2026 Anil Belur <askb23@gmail.com>
// SPDX-License-Identifier: Apache-2.0
//
// PreToolUse guard: block Read/Edit/Write on secret files
// (.env variants and the local Google OAuth token). .env.example
// is intentionally allowed.

let data = "";
process.stdin.on("data", (chunk) => {
  data += chunk;
});
process.stdin.on("end", () => {
  let input;
  try {
    input = JSON.parse(data);
  } catch {
    // Fail secure: if hook input can't be parsed we cannot verify the target,
    // so block rather than risk leaking a secret file.
    console.error("[Hook] BLOCKED: could not parse tool input");
    process.exit(2);
  }
  const filePath = input.tool_input?.file_path || "";
  const isSecret = /(^|\/)\.env|(^|\/)secrets\/|gcal-token\.json$/.test(filePath);
  const isExample = /(^|\/)\.env\.example$/.test(filePath);
  if (isSecret && !isExample) {
    console.error(`[Hook] BLOCKED: secret file ${filePath}`);
    process.exit(2);
  }
});
