# Delta Spec: capital-session (modified capability)

**Change:** ws-candle-ingestion
**Capability:** capital-session
**Status:** modified
**Phase:** spec

---

## Overview

`CapitalSession.authenticate()` is modified to capture the `streamingHost` field from the POST /session response body and expose it via a new `streaming_host: str` property. The `SessionTokens` return type and `tokens()` behavior are unchanged.

---

## MODIFIED Requirements

**CS-01.** `CapitalSession.authenticate()` SHALL parse the POST /session response body as JSON and store the value of the `streamingHost` key internally.

#### Scenario: streaming_host is captured from authenticate response body (AC-CS-1)
Given a mock HTTP client whose POST /session response body contains `{"streamingHost": "https://streaming.capital.com"}` with a valid CST and X-SECURITY-TOKEN header,
when `authenticate()` is called,
then `session.streaming_host` returns `"https://streaming.capital.com"`.

---

**CS-02.** `CapitalSession` SHALL expose a `streaming_host: str` property. Accessing this property before `authenticate()` has been called successfully SHALL raise `RuntimeError`.

#### Scenario: streaming_host raises before authenticate (AC-CS-2)
Given a freshly constructed `CapitalSession`,
when `session.streaming_host` is accessed before `authenticate()`,
then `RuntimeError` is raised.

---

**CS-03.** `CapitalSession.authenticate()` SHALL continue to return `SessionTokens` (unchanged return type). The `SessionTokens` dataclass SHALL NOT be modified.

#### Scenario: authenticate still returns SessionTokens (AC-CS-3)
Given the same mock HTTP client as AC-CS-1,
when `authenticate()` is called,
then the return value is a `SessionTokens` with the correct `cst` and `security_token` values (unchanged behavior).

---

**CS-04.** `CapitalSession.tokens()` behavior SHALL remain unchanged.

#### Scenario: tokens() unaffected by the streaming_host addition (AC-CS-4)
Given `authenticate()` has been called,
when `session.tokens()` is called,
then it returns the same `SessionTokens` as the `authenticate()` return value.
