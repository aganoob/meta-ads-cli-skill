# Security Policy

## Supported Versions

Security fixes are accepted for the current repository state on `main`.

## Reporting a Vulnerability

Please report security issues privately through GitHub's vulnerability reporting
feature when available. If that is not available, open a minimal issue that does
not include exploit details, secrets, tokens, account IDs, or private business
data.

## Sensitive Data

Do not include the following in issues, pull requests, tests, or documentation:

- Meta access tokens or system-user tokens.
- App IDs paired with app secrets.
- Business Manager IDs, ad account IDs, catalog IDs, dataset IDs, or Page IDs
  from private accounts unless they are intentionally public test data.
- Screenshots or exports containing customer, billing, campaign, or performance
  data.

The skill should continue to guide users toward local CLI execution and concise
summaries rather than copying sensitive account data into chat or commits.
