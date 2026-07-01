# Config Startup Validation and Environment Contract

## Purpose

This spec captures the four observable contracts corrected by `capital-adapter-hardening`.
No new domain capabilities are introduced; each requirement fixes a config defect that was
verifiably wrong against the Capital.com demo API or the strategy adapter's runtime contract.

---

## Requirements

### Requirement: Warmup Validator Enforces Strategy Adapter Minimum

The startup config validator MUST reject any `WARMUP_BARS` value that is below the strategy
adapter's required candle count (`_REQUIRED_CANDLES = 128`). The previous threshold
(`max(L_FROZEN, ATR_PERIOD) = 32`) was incorrect and allowed runtime failures at the adapter.

#### Scenario: Buffer below adapter minimum is rejected at startup

- GIVEN `WARMUP_BARS` is set to `64` (above the old threshold of 32, below the real minimum of 128)
- WHEN config is loaded and the startup validator runs
- THEN config loading MUST fail
- AND the error message MUST reference the insufficient warmup buffer (e.g. "warmup" or "WARMUP_BARS")

#### Scenario: Buffer at adapter minimum is accepted

- GIVEN `WARMUP_BARS` is set to `128`
- WHEN config is loaded and the startup validator runs
- THEN config loading MUST succeed

#### Scenario: Buffer above adapter minimum is accepted

- GIVEN `WARMUP_BARS` is set to `256`
- WHEN config is loaded and the startup validator runs
- THEN config loading MUST succeed

#### Scenario: Default warmup value passes validator without any env override

- GIVEN no `WARMUP_BARS` environment variable is set
- WHEN config is loaded
- THEN the resolved `warmup_bars` value MUST be `128`
- AND the startup validator MUST NOT raise an error

---

### Requirement: API Key Read from CAPITAL_API_KEY

Config MUST read the Capital.com API key from the environment variable `CAPITAL_API_KEY`.
The old variable name `API_KEY` MUST NOT be used for this purpose.

#### Scenario: CAPITAL_API_KEY set, API_KEY absent — load succeeds

- GIVEN `CAPITAL_API_KEY` is set to a non-empty value
- AND `API_KEY` is not set
- WHEN `load_config()` is called
- THEN config loading MUST succeed
- AND the resolved API key value MUST equal the value of `CAPITAL_API_KEY`

#### Scenario: Only legacy API_KEY set — load fails with missing-variable error

- GIVEN `API_KEY` is set to a non-empty value
- AND `CAPITAL_API_KEY` is not set
- WHEN `load_config()` is called
- THEN config loading MUST fail
- AND the error MUST indicate a missing required environment variable

---

### Requirement: Default Trade Size Is a Valid Capital Deal Size

When no `SIZE` environment variable is provided, the default `trade_size` MUST be `1000`.
This clears Capital.com's `minDealSize = 100` constraint.

#### Scenario: No SIZE env var — default resolves to 1000

- GIVEN the `SIZE` environment variable is not set
- WHEN `load_config()` is called
- THEN the resolved `trade_size` MUST equal `1000`

**Note:** There is no meaningful behavioral scenario beyond verifying the literal default value.
No startup validator enforces this floor at config load time (size validation is deferred to
the adapter layer per the DIP deferral in the proposal).

---

### Requirement: Demo Base URL Resolves to Verified Capital Host

In demo mode, the base URL MUST be `https://demo-api-capital.backend-capital.com/api/v1`.
The previous value pointed at an unresolvable host and caused all demo API calls to fail.

#### Scenario: Demo mode base URL ends with verified host path

- GIVEN the bot is configured in demo mode
- WHEN `load_config()` is called
- THEN `base_url` MUST end with `demo-api-capital.backend-capital.com/api/v1`

**Note:** The live base URL (`api-capital.backend-capital.com`) is corrected in the same
commit but is INFERRED, not API-verified. No test scenario is specified for it; verification
is deferred to the live-cutover smoke test.
