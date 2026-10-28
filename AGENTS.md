# AGENTS.md - l10n_sv_dte

Odoo 18 addon for El Salvador electronic invoicing (DTE) compliant with
Ministerio de Hacienda (MH) requirements. **This is an Odoo module, not a
standalone Python package** — it loads as an addon inside an Odoo instance.

## Architecture

The module follows strict Odoo conventions. Every file here is loaded by Odoo
in the order declared in `__manifest__.py`'s `data` list (data files first,
then views).

| Path | Purpose |
|------|---------|
| `__manifest__.py` | Addon metadata, version, dependency list, load order. **Bump the version** on every change (current: `18.0.1.22.0`). |
| `tests/` | Odoo tests (`TransactionCase`). Run with `odoo-bin --test-enable --test-tags=l10n_sv_dte`. Mock cert in `tests/common.py`. |
| `models/__init__.py` | Imports every model. **A model file not imported here is silently not loaded** — the original `l10n_sv_api.py` was missing from this file and `self.env['l10n_sv.api']` raised at runtime. |
| `models/account_move.py` | DTE state machine, JSON generation, JWS sign, MH send, invalidation. |
| `models/l10n_sv_signer.py` | JWS RS512 signer + MH certificate XML parser. **AbstractModel** — not a real table. |
| `models/l10n_sv_api.py` | MH HTTP client: auth, token cache, send, invalidate, contingencia. |
| `models/res_company.py` | Per-company MH config (NIT, certificate, ambiente, cod_estable). **Credentials are NOT here** — they live in `ir.config_parameter` (see Security below). |
| `data/*.csv` | Catalogs (CAT-008/009/012/013/015/016/019/022) and geographic data. `l10n_sv.municipio.csv` is generated from the official MH catalog (CAT-008 distritos + CAT-013 municipio per Decreto 762). **First column must be `id`** with a unique external XML-ID (e.g. `tr_sv_20`). |
| `security/ir.model.access.csv` | ACLs. **Every new `_name = '...'` model needs a row here** or superuser-only access. |
| `views/*.xml` | UI. Catalog views live in `l10n_sv_catalog_views.xml`. The QWeb DTE print report is in `report_l10n_sv_dte_invoice.xml`. |
| `docs/` | Functional documentation (one `.md` per topic). Mirror functional docs here, not in code comments. |

## Security: no hardcoded credentials, ever

This is an **open-source** module. Hardcoding credentials will leak through
git history forever.

- **API user/password** for MH → store in `ir.config_parameter` as
  `l10n_sv.api_user_<company_id>` and `l10n_sv.api_password_<company_id>`.
  Read at runtime via `ICP.get_param(...)`. **Never** add `Char` fields
  for these on `res.company`.
- **Certificate** (`.crt` XML with private key) → `res.company.l10n_sv_certificate`,
  a `Binary(attachment=True, groups='base.group_system')`. Read it only through
  `l10n_sv.signer._load_company_private_key()` (uses `sudo()`). Never expose it
  as a `Many2one('ir.attachment')` or a download action. Never commit `.crt`,
  `.key`, or `.pem` files to the repo.
- **Connector methods are private.** `l10n_sv.api` is an `AbstractModel`; every
  method that reads credentials or returns tokens starts with `_` so it is not
  callable by RPC. Public entry points (`cron_process_contingencia`,
  `action_test_mh_connection`) check `base.group_system`.
- **Every ACL row declares a group.** Catalogs: read `base.group_user`, write
  `account.group_account_manager`. `l10n_sv.dte.log`: read
  `account.group_account_invoice`, write/unlink only `base.group_system`.
- **Invoice lines** are filtered with `display_type == 'product'` (Odoo 17+).

## DTE state machine

`account.move.l10n_sv_dte_state` transitions are driven by button methods.
**Visibility of each button in `views/account_move_views.xml` depends on the
current state** — change state values only if you also update all four
`invisible=` attributes on the buttons.

```
draft → json_generated → signed → sent → processed (with selloRecepcion)
                                              ↘ rejected
                            signed → contingencia (if l10n_sv_dte_contingencia is checked)
```

State-change entry points: `action_generate_dte_json`, `action_sign_dte`,
`action_send_dte`, `action_invalidate_dte` (all in `models/account_move.py`).

## MH API environment

`res.company.l10n_sv_ambiente` is the switch:

- `00` (Test) → `https://apitest.dtes.mh.gob.sv`
- `01` (Producción) → `https://api.dtes.mh.gob.sv`

The URL is selected in `l10n_sv_api._get_base_url(ambiente)`. Tokens are
cached in `ir.config_parameter` keyed by company with 55-minute TTL (tokens
expire at 60min, we refresh 5min early). When MH returns a 401, the cached
token is cleared automatically so the next call re-authenticates.

## DTE schema versions

DTE type → JSON schema version, returned by `l10n_sv.api._get_dte_version()`
and embedded in `identificacion.version`:

| Types | Version |
|-------|---------|
| `01` FCF, `07` Ret, `08` Liq, `09` DocCont, `14` FSE, `15` Don | 2 |
| `11` FEX | 3 |
| `03` CCF, `04` NR, `05` NC, `06` ND | 4 |
| Invalidación | 3 |
| Contingencia | 4 |

Defined in `DTE_VERSION_MAP`, `INVALIDACION_VERSION` and `CONTINGENCIA_VERSION`
at top of `models/account_move.py`.

**Schema validation is mandatory.** Every generated DTE is validated against the
official MH JSON Schema in `data/schemas/` by `l10n_sv.dte.schema._validate()`
in `action_generate_dte_json` and again in `action_sign_dte`. Shipped: `01`
(`fe-f-v2.json`), `03` (`fe-ccf-v4.json`), `05` (`fe-nc-v4.json`) and `06` (`fe-nd-v4.json`); add the schema to
`DTE_SCHEMAS` in `models/l10n_sv_dte_schema.py` before supporting a new type.
Never send a key the schema does not declare (`additionalProperties: false`).
Validation uses `Decimal` because `multipleOf: 1e-08` fails with Python floats.
In NC/ND (and FCF) the IVA goes only in `totalIva`; never repeat it as tributo
`20` in `tributos` (confirmed against MH test environment: duplicated IVA is
rejected). `test_dte_schema.test_12_nc_matches_schema` guards this.
Addresses need `l10n_sv.municipio.municipio_mh` and `distrito_mh` (2024
territorial division); `codEstable`/`codPuntoVenta` must be `M001`/`P001` style.

## What does NOT exist here

There is no test suite, no CI, no linter, no formatter, no `pyproject.toml`,
no `setup.py`, no `Makefile`, no pre-commit config. **All verification runs
inside an Odoo instance** (install the addon, exercise it via UI, tail
`odoo.log`). If you add tests, put them in `tests/` per Odoo convention and
declare the test tag in `__manifest__.py`. If you add CI, use a matrix over
Odoo `18.0` with a Postgres service.

## Conventions

- **No comments in code** unless the user explicitly asks. The original
  `account_move.py` had a Spanish docstring on `action_generate_dte_json` —
  leave it as an exception only if the user requests documentation.
- **Field names** use the `l10n_sv_` prefix (Odoo standard for
  localization modules) — never `sv_` or `l10n_`.
- **CSV id column** must be a stable external XML-ID. For catalogs the
  convention is `<prefix>_sv_<code>` (e.g. `tr_sv_20` for tributo 20).
- **CAT-019 actividad_economica** has 989 CIIU Rev 4 codes from BCR.
  `description` is the field name (not `name`) — the model is reused by
  `res.company.l10n_sv_cod_actividad_id`.
- **NIT/NRC stored without dashes** — `action_generate_dte_json` strips
  non-digits before sending to MH. Do the same in any new code path.

## Common mistakes to avoid

- Adding a model file and forgetting to import it in `models/__init__.py`.
- Adding a model and forgetting a row in `security/ir.model.access.csv`.
- Forgetting to bump `__manifest__.py` version (Odoo uses it for upgrade
  detection — same version = no upgrade).
- Hardcoding the `apitest` URL in a model when the user has set
  `l10n_sv_ambiente = '01'`. Always go through `_get_base_url()`.
- Reading credentials from `res.company` fields. They aren't there.
- Committing `graphify-out/` — it's a dev tool's knowledge graph, not
  part of the module. Already gitignored.
- Writing `l10n_sv_dte_*` state/sello/control fields with `write()`. They are in
  `L10N_SV_DTE_PROTECTED_FIELDS`; flow methods use `_l10n_sv_write()`.
- Calling `l10n_sv.api` without `company=move.company_id` (multi-company).
- Logging an error and re-raising in the same transaction: the rollback erases
  the log. Persist state + `l10n_sv.dte.log` and return a notification.
- Moving a DTE with `selloRecepcion` out of `processed` on a failed invalidation.
  A sealed DTE never returns to draft and is never re-sent.
- Adding a button to the invoice header without a corresponding
  `invisible=` clause that reflects the DTE state.

## Phase status

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | Done | Bug fixes, fields, credential migration, UUID/numeroControl auto-gen |
| 2 | Done | Catalog models + 989 CIIU codes loaded from CSV |
| 3 | Done | JWS signer, MH API client, contingency, invalidation |
| 4 | Done | Complete JSON DTE: `resumen`, `documentoRelacionado`, `extension`, `pagos` |
| 5 | Done | Full DTE flow + state machine polish + wizard (log, resend, reset, batch, cron contingencia) |
| 6 | Done | QR generation + QWeb DTE print report (PDF/HTML) |
| 7 | Done | Test suite (5 test files, 50+ tests) + per-topic docs (`docs/instalacion.md`, `docs/catalogos.md`, `docs/api-mh.md`, `docs/flujo-dte.md`, `docs/firma-digital.md`) |
