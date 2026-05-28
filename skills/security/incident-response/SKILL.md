---
name: incident-response
description: "Triage and respond to a security incident: contain, assess, remediate, document."
version: 1.0.0
author: birkin
license: MIT
metadata:
  birkin:
    tags: [security, incident, response]
---

# Incident Response

Systematically respond to a security incident: contain the immediate threat,
assess scope and impact, identify root cause, remediate, and document findings.

## When to Use

- When alerted to a potential breach, unauthorized access, or malicious activity.
- After discovering a vulnerability in production.

## When NOT to Use

- For suspected false alarms without evidence (investigate first with read_file/logs).

## Procedure

1. **Contain** — identify affected systems (read_file on logs, config). Kill active
   sessions or revoke compromised credentials if needed (run_shell).
2. **Assess** — determine what data was accessed and when. Check logs for lateral
   movement, privilege escalation, data exfiltration.
3. **Root Cause** — trace the attack vector (config flaw, unpatched service, weak
   secret, social engineering). Use read_file on system/app configs.
4. **Remediate** — fix the vulnerability, reset credentials, patch systems. Document
   each step with run_shell output.
5. **Document** — write incident report: timeline, what happened, who, impact,
   fixes applied, prevention going forward.

## Output

- Incident timeline (when discovered, first evidence, scope).
- Root cause and affected components.
- Remediation checklist with status.
- Post-incident recommendations.
