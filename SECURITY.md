# Security Policy

## Reporting Security Issues

Please report security issues privately through GitHub rather than opening a public issue with exploit details or secrets.

## Secrets

Do not publish Discord webhook URLs, Henrik API keys, tokens, passwords, or local secret files.

ClipDis is designed to store secrets locally through keyring/Windows Credential Manager when available, with a local fallback. Logs, diagnostics, and UI surfaces should redact secrets.

## Logs and Diagnostics

Before sharing logs or diagnostic output, verify that webhook URLs and API keys are redacted. If you accidentally publish a webhook/API key, rotate it immediately.
