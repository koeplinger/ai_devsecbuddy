# data/

Runtime home of the **vulnerability ledger** — the central SQLite database where
AI DevSecBuddy records every run, baseline, attack vector, and `Finding`. At
runtime the [`devsecbuddy`](../devsecbuddy/) `Ledger` component and the
[`../backend/`](../backend/) service read and write the ledger file here (by
convention `data/ledger.db`), giving an auditable, replayable security record of
every probe run against every tile.

The ledger database is a **runtime artifact and is gitignored** — see the root
`.gitignore` (`data/*.db`, `*.sqlite3`). Only this README is tracked; the
`.db` file is created on first run and must never be committed (it may contain
generated repro payloads and evidence). The exact table/column schema is fixed
by the Design Bible and documented in
[`../docs/vulnerability-ledger.md`](../docs/vulnerability-ledger.md).

> Status: **docs-first prototype.** No database exists yet in this deliverable;
> this folder is a placeholder for the runtime ledger described in the docs.
