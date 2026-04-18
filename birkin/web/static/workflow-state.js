/* Birkin Workflow — Shared state, palette, and utility functions */

(function () {
  const B = window.birkin;

  const NODE_W = 140, NODE_H = 56, PORT_R = 6;

  const PALETTE_DEF = [
    { groupKey: "ng_io", items: [
      { type: "input",           icon: "\u2709",    labelKey: "nt_input",         descKey: "nd_input",         color: "nc-io" },
      { type: "output",          icon: "\u2705",    labelKey: "nt_output",        descKey: "nd_output",        color: "nc-io" },
      { type: "webhook-trigger", icon: "\u{1F310}", labelKey: "nt_webhook",       descKey: "nd_webhook",       color: "nc-platform" },
    ]},
    { groupKey: "ng_ai", items: [
      { type: "llm",             icon: "\u2728",    labelKey: "nt_llm",           descKey: "nd_llm",           color: "nc-ai" },
      { type: "llm-stream",      icon: "\u{1F4A8}", labelKey: "nt_llm_stream",    descKey: "nd_llm_stream",    color: "nc-ai" },
      { type: "classifier",      icon: "\u{1F3AF}", labelKey: "nt_classifier",    descKey: "nd_classifier",    color: "nc-ai" },
      { type: "embedder",        icon: "\u{1F9F2}", labelKey: "nt_embedder",      descKey: "nd_embedder",      color: "nc-ai" },
      { type: "summarizer",      icon: "\u{1F4DD}", labelKey: "nt_summarizer",    descKey: "nd_summarizer",    color: "nc-ai" },
      { type: "translator",      icon: "\u{1F30D}", labelKey: "nt_translator",    descKey: "nd_translator",    color: "nc-ai" },
    ]},
    { groupKey: "ng_tools", items: [
      { type: "tool-dispatch",   icon: "\u2699",    labelKey: "nt_tool_dispatch", descKey: "nd_tool_dispatch", color: "nc-tool" },
      { type: "web-search",      icon: "\u{1F50D}", labelKey: "nt_web_search",    descKey: "nd_web_search",    color: "nc-tool" },
      { type: "code-exec",       icon: "\u{1F4BB}", labelKey: "nt_code_exec",     descKey: "nd_code_exec",     color: "nc-tool" },
      { type: "api-call",        icon: "\u{1F517}", labelKey: "nt_api_call",      descKey: "nd_api_call",      color: "nc-tool" },
      { type: "file-read",       icon: "\u{1F4C4}", labelKey: "nt_file_read",     descKey: "nd_file_read",     color: "nc-tool" },
      { type: "file-write",      icon: "\u{1F4BE}", labelKey: "nt_file_write",    descKey: "nd_file_write",    color: "nc-tool" },
    ]},
    { groupKey: "ng_memory", items: [
      { type: "memory-search",     icon: "\u{1F50E}", labelKey: "nt_mem_search",  descKey: "nd_mem_search",  color: "nc-memory" },
      { type: "memory-write",      icon: "\u{1F4DD}", labelKey: "nt_mem_write",   descKey: "nd_mem_write",   color: "nc-memory" },
      { type: "context-inject",    icon: "\u{1F4E5}", labelKey: "nt_ctx_inject",  descKey: "nd_ctx_inject",  color: "nc-memory" },
      { type: "knowledge-extract", icon: "\u{1F9E0}", labelKey: "nt_knowledge",   descKey: "nd_knowledge",   color: "nc-memory" },
    ]},
    { groupKey: "ng_control", items: [
      { type: "condition",       icon: "\u2747",    labelKey: "nt_condition",      descKey: "nd_condition",    color: "nc-control" },
      { type: "merge",           icon: "\u{1F500}", labelKey: "nt_merge",          descKey: "nd_merge",        color: "nc-control" },
      { type: "loop",            icon: "\u{1F504}", labelKey: "nt_loop",           descKey: "nd_loop",         color: "nc-control" },
      { type: "delay",           icon: "\u23F3",    labelKey: "nt_delay",          descKey: "nd_delay",        color: "nc-control" },
      { type: "parallel",        icon: "\u2261",    labelKey: "nt_parallel",       descKey: "nd_parallel",     color: "nc-control" },
      { type: "prompt-template", icon: "\u{1F4CB}", labelKey: "nt_prompt_tpl",     descKey: "nd_prompt_tpl",   color: "nc-control" },
    ]},
    { groupKey: "ng_gates", items: [
      { type: "code-review",    icon: "\u{1F50F}", labelKey: "nt_code_review",    descKey: "nd_code_review",    color: "nc-gate" },
      { type: "human-review",   icon: "\u{1F464}", labelKey: "nt_human_review",   descKey: "nd_human_review",   color: "nc-gate" },
      { type: "guardrail",      icon: "\u{1F6E1}", labelKey: "nt_guardrail",      descKey: "nd_guardrail",      color: "nc-gate" },
      { type: "validator",      icon: "\u2714",    labelKey: "nt_validator",       descKey: "nd_validator",       color: "nc-gate" },
      { type: "test-runner",    icon: "\u{1F9EA}", labelKey: "nt_test_runner",     descKey: "nd_test_runner",     color: "nc-gate" },
    ]},
    { groupKey: "ng_platform", items: [
      { type: "telegram-send",  icon: "\u2708",    labelKey: "nt_tg_send",        descKey: "nd_tg_send",        color: "nc-platform" },
      { type: "email-send",     icon: "\u2709",    labelKey: "nt_email_send",     descKey: "nd_email_send",     color: "nc-platform" },
      { type: "notify",         icon: "\u{1F514}", labelKey: "nt_notify",          descKey: "nd_notify",          color: "nc-platform" },
    ]},
  ];

  function getPalette() {
    const t = B.t;
    return PALETTE_DEF.map((g) => ({
      group: t(g.groupKey),
      items: g.items.map((it) => ({ ...it, label: t(it.labelKey), desc: t(it.descKey) })),
    }));
  }

  function getPaletteFlat() {
    const flat = {};
    getPalette().forEach((g) => g.items.forEach((it) => { flat[it.type] = it; }));
    return flat;
  }

  // Shared mutable state
  B._wf = {
    NODE_W, NODE_H, PORT_R,
    container: B.$("view-workflow"),
    initialized: false,
    canvas: null, ctx: null,
    nodes: [], edges: [],
    pan: { x: 0, y: 0 }, zoom: 1,
    drag: null, connecting: null, hoveredNode: null, selectedNode: null,
    samplesOpen: false,
    currentWorkflowId: null,
    configPanel: null, samplesPanel: null,
    nodeIdCounter: 0,
    galleryEl: null,
    // Functions exposed for cross-module access
    getPalette,
    getPaletteFlat,
    draw: null,         // set by workflow-canvas.js
    showConfig: null,   // set by workflow-config.js
    closeConfig: null,  // set by workflow-config.js
    loadWorkflow: null, // set by workflow-config.js
  };
})();
