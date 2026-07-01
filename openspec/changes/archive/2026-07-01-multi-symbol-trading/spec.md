# Spec: multi-symbol-trading

## Purpose

Define the behavioral requirements for running the frozen fade strategy across six FX symbols in one process.
This change affects two components only: `config.py` (symbol/epic/size parsing) and `__main__.py` (use-case construction and poll loop).
All other modules are symbol-agnostic and MUST NOT be modified.

---

## Domain: Configuration

### Requirement: Multi-Symbol Config Parsing

The system MUST parse a list of trading symbols from environment variables and construct a per-symbol configuration (symbol identifier, broker epic, trade size) for each entry.

#### Scenario: All symbols configured correctly

- GIVEN the environment contains `SYMBOLS=EURUSD,USDJPY,GBPUSD,AUDUSD,USDCAD,USDCHF`
- AND each symbol has a corresponding epic defined (via explicit env var or convention)
- AND `SIZE` defaults to 1000
- WHEN the configuration is loaded
- THEN six `SymbolConfig` entries are produced, one per symbol
- AND each entry carries the correct epic and size value

#### Scenario: Per-symbol size override

- GIVEN `SYMBOLS=EURUSD,USDJPY` and `SIZE=1000` and `SIZE_USDJPY=2000`
- WHEN the configuration is loaded
- THEN the EURUSD entry has size 1000
- AND the USDJPY entry has size 2000

#### Scenario: Missing epic for a listed symbol

- GIVEN `SYMBOLS=EURUSD,GBPUSD` and no epic source resolves for `GBPUSD`
- WHEN the configuration is loaded
- THEN the process MUST raise a startup error naming the missing symbol (`GBPUSD`)
- AND the process MUST NOT start the poll loop

#### Scenario: Empty SYMBOLS value

- GIVEN `SYMBOLS` is set to an empty string or is absent
- WHEN the configuration is loaded
- THEN the process MUST raise a startup error indicating no symbols are configured

#### Scenario: Duplicate symbol in list

- GIVEN `SYMBOLS=EURUSD,EURUSD`
- WHEN the configuration is loaded
- THEN the process MUST raise a startup error naming the duplicate

---

## Domain: Process Entrypoint

### Requirement: One Use Case Per Symbol at Startup

The system MUST construct exactly one `RunTradingCycleUseCase` per configured symbol during startup, before entering the poll loop.

#### Scenario: Six symbols configured

- GIVEN six valid `SymbolConfig` entries
- WHEN the entrypoint initializes
- THEN six `RunTradingCycleUseCase` instances are created, one per symbol
- AND each instance is bound to its own symbol, epic, and size

#### Scenario: Broker session authenticated once per boundary

- GIVEN the poll loop is at a boundary
- WHEN the loop iteration begins
- THEN `session.authenticate()` is called once
- AND THEN each use case is executed in sequence

### Requirement: Sequential Per-Symbol Poll Execution

The system MUST iterate all symbol use cases sequentially within each poll boundary.
A failure in one symbol's execution cycle MUST be caught, logged with the symbol identifier, and MUST NOT abort the remaining symbols in the same boundary or future boundaries.

#### Scenario: All symbols execute without error

- GIVEN six use cases are registered
- WHEN a poll boundary fires
- THEN all six use cases execute in sequence within that boundary
- AND the loop schedules the next boundary normally

#### Scenario: One symbol raises an exception

- GIVEN six use cases are registered
- AND the third symbol's use case raises an unexpected exception
- WHEN that boundary is executed
- THEN the exception is caught and logged with the offending symbol name
- AND the remaining three symbols still execute in the same boundary
- AND the loop schedules the next boundary normally

#### Scenario: All symbols raise exceptions in the same boundary

- GIVEN six use cases are registered
- AND every use case raises an exception
- WHEN that boundary is executed
- THEN each exception is caught and logged individually
- AND the loop schedules the next boundary normally (process does not crash)

### Requirement: Reconciler Symbol-Agnosticism Confirmed

The reconciler process (`reconcile_closed_trades.py`) operates by deal ID only and MUST NOT require modification to support multiple symbols.

#### Scenario: Multi-symbol trades in the journal

- GIVEN closed trades from multiple symbols exist in the journal
- WHEN the reconciler runs
- THEN it processes all trades regardless of symbol
- AND no symbol-specific logic is required in the reconciler
