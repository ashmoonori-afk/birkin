# Birkin for VS Code

The official VS Code surface for a local Birkin runtime. It sends the active selection and open-file list, reviews plans before execution, opens proposed file changes in VS Code's diff editor, resolves actions through Birkin's approval queue, restores Birkin checkpoints, and shows live runtime status.

## Run from source

```bash
cd vscode-extension
npm install
npm run compile
birkin gateway   # default local HTTP channel: 127.0.0.1:8788
birkin web --no-browser
code --extensionDevelopmentPath="$PWD"
```

The extension discovers the dashboard capability from `~/.birkin/web_session.json`. Configure `birkin.gatewayUrl` if your gateway uses a different port. The gateway requires a capability by default and automatically creates `BIRKIN_HOME/gateway_http_token` when `BIRKIN_HTTP_TOKEN` is not configured. Copy the generated file value, or the configured environment value, to `birkin.gatewayToken`.

Use the Command Palette commands beginning with **Birkin:**. Start with **Review Plan Before Execution**, inspect the plan, and choose **Execute Plan** only when ready. Pending file proposals open in VS Code's native diff editor before Approve/Reject.
