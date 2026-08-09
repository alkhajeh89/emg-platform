# EMG ADR-038 — Human Identity Delegation Architecture

**Status:** Accepted

**Owner:** EMG Founder

**Architect:** EMG Founder

**Decision Authority:** Project Architect

**Decision Date:** 2026-08-07

**Related:**
ADR-014 (Enterprise Presentation Architecture),
ADR-025 (Knowledge Graph Tenant Authorization),
ADR-026 (Classification Enforcement),
ADR-034 (Security State and Service Trust),
ADR-035 (Human Principal Authentication),
ADR-036 (Application and BFF Boundary)

**Supersedes:** None

**Closes:** Former ADR-036 §5 Delegation Sub-Decision

> **Implementation status — 2026-08-09.** The mandatory Keycloak 25
> capability verification passed and Phase 2B subsequently implemented this
> architecture in the Studio BFF and delegated-credential-aware Knowledge Graph
> boundary, including synchronous fail-closed audit attribution. Production
> realm values, secrets, TLS, and deployment remain operational prerequisites.

---

# Chapter I — Purpose

## 1.1 Objective

This Architecture Decision Record establishes the authoritative architecture governing delegated human identity throughout the Enterprise Memory Graph (EMG) platform.

Its purpose is to define the security semantics, trust model, authorization semantics, audit semantics, and architectural invariants governing delegated execution of Human Principals through the mandatory Backend-for-Frontend (BFF) architecture.

This ADR closes the intentional architectural gap left unresolved by ADR-035 (Human Principal Authentication) and ADR-036 (Application and BFF Boundary).

---

## 1.2 Scope

This ADR governs only delegated human identity.

Specifically, this ADR defines:

- delegated identity semantics;
- delegated authorization semantics;
- delegated audit semantics;
- delegated execution security invariants;
- implementation constraints;
- capability verification requirements;
- architectural conformance requirements.

This ADR does **not** redefine:

- browser authentication;
- authentication protocols;
- session management;
- BFF architecture;
- authorization policy;
- policy evaluation;
- tenant authorization;
- classification enforcement;
- Decision Query behaviour;
- PostgreSQL authoritative persistence;
- Neo4j projection architecture.

Those concerns remain governed by their respective accepted ADRs.

This ADR complements ADR-035 (Human Principal Authentication) and ADR-036
(Application and BFF Boundary). ADR-035 governs browser authentication,
ADR-036 governs the application and BFF boundary, and this ADR governs only
the downstream delegation of Human Principal identity beyond the BFF.

---

## 1.3 Architectural Authority

This ADR is the authoritative architectural specification governing delegated human execution throughout EMG.

No service, application, gateway, middleware, adapter, plugin, transport, connector, or Backend-for-Frontend implementation may introduce an alternative delegated identity model outside the constraints defined herein.

Future delegation technologies SHALL conform to the semantics defined by this ADR rather than redefining them.

---

# Chapter II — Problem Statement

## 2.1 Existing Architecture

The accepted EMG architecture defines the following target request path.
Implementation status for each element is recorded separately and is not
implied by this diagram:

```text
Browser
    ↓
Backend-for-Frontend (ADR-035 and ADR-036 boundary)
    ↓
Delegated Credential (ADR-038 boundary)
    ↓
Platform Service
```

This trust path does not add a product surface or change any service's
persistence model. Where persistence is used, PostgreSQL remains authoritative
and Neo4j remains a derived non-authoritative projection.

---

## 2.2 Existing Capability

Repository analysis confirms that EMG already provides:

- the Human Principal model and existing non-browser session machinery;
- authenticated Service Principals;
- transport-neutral application services;
- service-to-service authentication;
- policy-based authorization;
- tenant isolation;
- classification enforcement;
- immutable audit infrastructure;
- authoritative revision history.

These capabilities remain unchanged.

---

## 2.3 Architectural Gap

Before ADR-038 was accepted, repository analysis confirmed one unresolved
trust boundary.

Platform services currently authenticate only registered Service Principals.

Application services already support authenticated Human Principals internally.

At that time, no accepted architecture specified how an authenticated browser
session securely delegated Human Principal identity through the mandatory
Backend-for-Frontend into downstream platform services.

Consequently, the following semantics were previously undefined and are now
governed by this ADR:

- delegated identity construction;
- delegated execution semantics;
- delegated authorization subject propagation;
- delegated audit attribution;
- Delegated Credential semantics.

Implementation of Phase 2B before the mandatory capability verification
succeeds would violate this accepted architecture and remains prohibited.

---

## 2.4 Architectural Decision

This ADR establishes the authoritative delegated execution architecture for EMG.

OAuth 2.0 Token Exchange (RFC 8693) is the accepted authoritative delegation
architecture, subject to the complete EMG Delegation Profile and every
constraint defined by this ADR.

Acceptance records the architecture decision; it does not establish capability
or implementation. Until successful verification has completed, Phase 2B
implementation SHALL remain blocked.

---

# Chapter III — Architecture Principles

## Principle 1 — Single Authoritative Identity

Every authorization decision SHALL be based upon exactly one authenticated authorization principal.

---

## Principle 2 — Explicit Trust Boundaries

Trust SHALL exist only across explicitly defined architectural boundaries.

---

## Principle 3 — Separation of Authentication and Authorization

Authentication establishes identity.

Authorization evaluates permissions.

Neither concern SHALL assume responsibility for the other.

---

## Principle 4 — Separation of Human and Service Identity

Human identities and service identities SHALL remain distinct architectural concepts.

Delegated execution SHALL preserve both identities independently.

---

## Principle 5 — Transport Independence

Application services SHALL remain unaware of:

- OAuth
- Browser sessions
- Cookies
- JWT structure
- Token Exchange protocols

---

## Principle 6 — Policy Independence

Delegation mechanisms SHALL NOT alter Policy Engine semantics.

---

## Principle 7 — Audit Completeness

Every protected operation SHALL remain attributable to:

- authenticated Human Principal;
- authenticated Acting Service;
- authorization subject;
- protected resource;
- authorization decision.

---

## Principle 8 — Least Privilege

Delegation SHALL never elevate privilege.

Delegation MAY reduce privilege.

---

## Principle 9 — Authoritative Validation

Identity SHALL originate only from cryptographically verifiable authority.

---

## Principle 10 — Architecture Stability

This ADR introduces only the missing delegation trust boundary.

Existing EMG architecture remains unchanged.

---

## Principle 11 — Mechanism Independence

Delegated execution SHALL remain independent of any particular delegation technology.

Any future delegation mechanism SHALL satisfy every architectural invariant defined by this ADR.

---

# Chapter IV — Trust Boundaries

## 4.1 Trust Boundary Objective

The EMG platform SHALL explicitly define every trust transition involved in delegated execution.

Trust SHALL never be implied by:

- network location;
- deployment topology;
- infrastructure ownership;
- service ownership.

Every trust transition SHALL perform explicit identity validation.

---

## 4.2 Trust Domains

The delegated execution architecture consists of six trust domains.

### Trust Domain A — Browser

The Browser is an untrusted execution environment.

Browser authentication is governed exclusively by ADR-035, and the Browser-to-
BFF boundary is governed exclusively by ADR-036. For the downstream delegation
model governed by this ADR, the Browser SHALL:

- never issue delegated identities;
- never issue platform credentials;
- never evaluate authorization.

---

### Trust Domain B — Studio BFF

The Studio BFF is the only trusted browser application boundary.

Its session and Browser-boundary responsibilities are governed exclusively by
ADR-035 and ADR-036. For downstream delegation governed by this ADR, the BFF
SHALL:

- establish delegated execution;
- authenticate its Acting Service identity downstream;
- request Delegated Credentials;
- propagate correlation identifiers.

The BFF SHALL NOT:

- issue Delegated Credentials;
- evaluate authorization;
- access persistence;
- become an identity provider.

---

### Trust Domain C — Authorization Authority

The Authorization Authority SHALL be the only component permitted to issue Delegated Credentials.

It SHALL validate:

- the approved delegation input representing the authenticated Human Principal;
- requesting application;
- delegation policy;
- audience;
- scope;
- credential lifetime.

---

### Trust Domain D — Platform Services

Every protected service SHALL independently validate:

- credential integrity;
- issuer;
- audience;
- expiry;
- tenant;
- authorization principal.

---

### Trust Domain E — Policy Engine

The Policy Engine SHALL remain independent of transport and delegation technologies.

---

### Trust Domain F — Authoritative Persistence

PostgreSQL remains the sole authoritative persistence boundary.

Neo4j SHALL never become an Authorization Authority.

---

# Chapter V — Identity Model

## 5.1 Identity Objective

The EMG platform SHALL maintain explicit separation between:

- authentication identity;
- delegated identity;
- authorization identity;
- audit attribution.

Identity ambiguity is prohibited.

---

## 5.2 Principal Types

This ADR governs delegated execution initiated by Human Principals.

Accordingly, the following principal types participate in the delegated identity model.

### Human Principal

Represents one authenticated human user.

A Human Principal SHALL:

- uniquely identify one authenticated user;
- remain immutable throughout delegated execution;
- never represent an application or service.

---

### Service Principal

Represents one authenticated platform service.

A Service Principal SHALL:

- uniquely identify one authenticated service;
- authenticate machine-to-machine communication;
- remain independent of the Human Principal.

---

### Delegated Principal

Represents delegated execution of one authenticated Human Principal through one authenticated Service Principal.

A Delegated Principal SHALL preserve:

- authenticated Human Principal identity;
- authenticated Acting Service;
- tenant context;
- authorization context;
- classification clearance.

Delegated execution SHALL preserve both identities independently.

The Delegated Principal SHALL remain immutable for the lifetime of the delegated execution context.

---

## 5.3 Principal Immutability

Once constructed by the Authorization Authority, a Delegated Principal SHALL NOT be modified by:

- the Browser;
- the Studio BFF;
- Platform Services;
- the Policy Engine;
- the Audit Service.

Any modification SHALL invalidate delegated execution.

---

## 5.4 Identity Construction

Only the Authorization Authority may construct a Delegated Principal.

No Browser, Studio BFF, Platform Service, gateway, middleware, or transport component may independently construct delegated identities.

---

## 5.5 Delegated Execution Context

For the purposes of this ADR, a delegated execution context is defined as:

> the complete authorization context established for one authenticated Human Principal request targeting one downstream audience through one authenticated Acting Service.

A delegated execution context MAY include multiple internal processing steps within the same downstream service.

It SHALL NOT span multiple downstream audiences.

Whenever execution requires access to an additional downstream audience, a new delegated execution context SHALL be established using a newly issued Delegated Credential.

---

## 5.6 Identity Lifetime

Delegated Principals SHALL exist only for the lifetime of their delegated execution context.

Their lifetime SHALL NOT exceed the validity of the Delegated Credential under which they were established.

---

## 5.7 Identity Independence

Authentication identity,

delegated identity,

authorization identity,

and audit attribution

SHALL remain architecturally independent.

No implementation may merge these concepts into a mutable identity object.

---

# Chapter VI — Delegation Architecture

## 6.1 Accepted Architectural Direction

The accepted architectural direction for EMG is OAuth 2.0 Token Exchange (RFC 8693).

This decision is based upon the completed architectural assessment, repository analysis, standards review, and security evaluation.

The selection of RFC 8693 does not alter the architectural semantics defined by this ADR.

This ADR governs architectural behaviour rather than protocol-specific implementation.

RFC 8693 is the adopted implementation mechanism for satisfying the architectural requirements defined herein, but does not replace or redefine those requirements.

---

## 6.2 Architectural Decision

EMG SHALL adopt OAuth 2.0 Token Exchange conforming to RFC 8693 as the authoritative delegated identity architecture. Any implementation remains subject to successful verification of the complete EMG Delegation Profile defined by this ADR.

This ADR is Accepted. Acceptance records the architecture decision and does not imply implementation. Phase 2B SHALL remain blocked until capability verification has successfully completed.

---

## 6.3 Required EMG Delegation Profile

The Authorization Authority SHALL demonstrate support for:

- authenticated Human Principal preservation;
- independently identifiable Acting Service;
- audience restriction;
- scope reduction only;
- tenant integrity;
- clearance integrity;
- confidential-client authentication;
- independent downstream validation;
- bounded credential lifetime;
- complete audit attribution.

---

## 6.4 Architectural Constraints

The selected delegation architecture SHALL satisfy every Security Invariant defined by this ADR.

No proprietary delegation mechanism may replace the adopted architecture without approval through a future Architecture Decision Record.

---

## 6.5 Capability Verification Requirement

Capability verification SHALL be completed in a dedicated non-production environment.

Successful verification is mandatory before implementation of Phase 2B.

Until successful verification has completed, Phase 2B SHALL remain blocked.

---

## 6.6 Relationship to ADR-036

Acceptance of this ADR resolves the open delegation sub-decision recorded in ADR-036 Section 5.

ADR-036 continues to govern the Browser-to-BFF architectural boundary.

ADR-038 is the authoritative specification governing delegated human identity beyond that boundary.

---

# Chapter VII — Delegation Credential Requirements

## 7.1 Objective

This chapter defines the mandatory properties that every Delegated Credential SHALL satisfy, regardless of the delegation technology selected by the EMG platform.

A Delegated Credential represents the authenticated execution context of one authenticated Human Principal acting through one authenticated Service Principal.

---

## 7.2 Credential Authority

Delegated Credentials SHALL be issued only by the designated Authorization Authority.

No Browser, Studio BFF, Platform Service, gateway, middleware, transport component, or intermediary may independently issue Delegated Credentials.

---

## 7.3 Mandatory Credential Properties

Every Delegated Credential SHALL contain, directly or through cryptographically verifiable claims:

- authenticated Human Principal;
- authenticated Acting Service;
- intended downstream audience;
- tenant identity;
- authorization scope;
- classification clearance;
- issuance timestamp;
- expiration timestamp;
- issuer identity;
- unique credential identifier.

No mandatory property SHALL be inferred from transport metadata.

---

## 7.4 Audience Restriction

Every Delegated Credential SHALL be issued for exactly one downstream audience.

A Delegated Credential SHALL NOT be accepted by services outside its intended audience.

Cross-audience credential reuse is prohibited.

---

## 7.5 Credential Lifetime

Delegated Credentials SHALL possess a bounded lifetime independent of browser sessions.

Credential lifetime SHALL remain as short as operationally practical.

Delegated Credentials SHALL expire automatically.

---

## 7.6 Credential Validation

Every downstream Platform Service SHALL independently validate:

- issuer;
- signature;
- audience;
- expiration;
- tenant identity;
- authorization principal.

Validation SHALL complete successfully before authorization evaluation begins.

---

## 7.7 Credential Confidentiality

Delegated Credentials SHALL never be exposed to:

- browsers;
- JavaScript;
- local storage;
- session storage;
- IndexedDB;
- client-side logging;
- browser developer tools through application logic.

Delegated Credentials SHALL remain server-side throughout their lifetime.

---

## 7.8 Credential Reuse

A Delegated Credential MAY be reused only while all of the following conditions remain true:

- the downstream audience is identical;
- the authenticated Human Principal is identical;
- the authenticated Acting Service is identical;
- the tenant identity is identical;
- the classification clearance is identical;
- the Delegated Credential remains valid and unexpired.

Credential reuse SHALL NOT extend the credential lifetime.

Credential reuse SHALL NOT bypass credential validation.

Any change to one or more of these attributes SHALL require issuance of a new Delegated Credential.

---

## 7.9 Credential Caching

Where credential caching is implemented for performance reasons, the cache SHALL be keyed, at minimum, by:

- Human Principal;
- Service Principal;
- downstream audience;
- tenant identity;
- classification clearance.

Credential caches SHALL never return a Delegated Credential issued for a different downstream audience.

Credential caches SHALL never extend credential validity beyond its original expiration time.

Credential caches SHALL remain entirely server-side.

---

## 7.10 Credential Revocation

Where immediate revocation is supported by the Authorization Authority, revoked Delegated Credentials SHALL immediately cease to authorize downstream requests.

Where immediate revocation is unavailable, Delegated Credentials SHALL rely upon their bounded lifetime together with mandatory revalidation of newly issued credentials.

Delegated Credentials SHALL never become an alternative source of authorization state.

---

# Chapter VIII — Authorization and Audit Semantics

## 8.1 Objective

Delegated execution SHALL preserve complete authorization semantics and complete audit attribution.

Delegation SHALL never modify authorization behaviour.

---

## 8.2 Authorization Subject

The authenticated Human Principal SHALL remain the authorization subject.

The Acting Service SHALL never become the authorization subject.

---

## 8.3 Acting Service

The Acting Service SHALL remain independently identifiable.

Platform services SHALL distinguish between:

- authorization subject;
- authenticated Acting Service.

These identities SHALL never be merged.

---

## 8.4 Policy Evaluation

The Policy Engine SHALL evaluate permissions solely against the authenticated authorization principal.

Delegation technology SHALL remain invisible to policy evaluation.

---

## 8.5 Tenant Authorization

Tenant identity SHALL originate exclusively from authenticated delegated identity.

Client-provided tenant identifiers SHALL never influence authorization.

---

## 8.6 Classification Enforcement

Classification enforcement SHALL remain unchanged.

Delegated execution SHALL neither bypass nor modify classification decisions.

---

## 8.7 Audit Attribution

Every delegated operation SHALL record:

- authenticated Human Principal;
- authenticated Acting Service;
- authorization decision;
- protected resource;
- tenant;
- classification;
- timestamp;
- correlation identifier.

---

## 8.8 Correlation

Correlation identifiers SHALL propagate unchanged across:

Browser

↓

Studio BFF

↓

Authorization Authority

↓

Platform Service

↓

Audit Service

Correlation identifiers SHALL NOT constitute identity.

---

## 8.9 Audit Integrity

Audit records SHALL remain:

- immutable;
- complete;
- cryptographically attributable;
- independently verifiable.

Loss of attribution SHALL constitute an audit failure.

---

# Chapter IX — Security Invariants

## 9.1 Purpose

This chapter defines the mandatory security properties that SHALL remain true for every delegated execution regardless of implementation technology.

These invariants are binding.

Violation of any invariant renders an implementation non-conformant.

---

## 9.2 Invariant — Immutable Human Subject

The authenticated Human Principal SHALL remain unchanged throughout delegated execution.

No component SHALL replace or modify the authorization subject.

---

## 9.3 Invariant — Independent Acting Service

Every Delegated Credential SHALL independently identify the authenticated Acting Service.

The authenticated Human Principal and Acting Service SHALL remain independently distinguishable.

---

## 9.4 Invariant — No Privilege Escalation

Delegation SHALL never increase:

- permissions;
- roles;
- clearance;
- tenant access.

Delegation MAY reduce privilege only.

---

## 9.5 Invariant — Audience Isolation

Delegated Credentials SHALL be valid for one downstream audience only.

Cross-audience credential reuse is prohibited.

---

## 9.6 Invariant — Tenant Integrity

Tenant identity SHALL remain unchanged from the originating authenticated session.

Tenant substitution is prohibited.

---

## 9.7 Invariant — Clearance Integrity

Classification clearance SHALL remain unchanged throughout delegated execution.

Clearance elevation is prohibited.

---

## 9.8 Invariant — Cryptographic Validation

Every Delegated Credential SHALL be cryptographically validated.

Network trust SHALL never replace identity validation.

---

## 9.9 Invariant — No Client-Controlled Identity

Identity SHALL never originate from:

- HTTP headers;
- browser parameters;
- cookies;
- local storage;
- JavaScript.

Only the Authorization Authority may establish delegated identity.

---

## 9.10 Invariant — Fail Closed

Delegation failures SHALL deny execution.

Fallback to anonymous, service-only, or inferred identity is prohibited.

---

## 9.11 Invariant — Bounded Lifetime

Delegated Credentials SHALL expire automatically.

Expired Delegated Credentials SHALL never be accepted.

---

## 9.12 Invariant — Complete Audit

Every delegated operation SHALL remain reconstructable using audit records alone.

Human Principal, Acting Service, authorization decision, tenant, and protected resource SHALL remain attributable.

---

## 9.13 Invariant Precedence

These Security Invariants constitute non-negotiable architectural requirements.

No implementation technology, product capability, deployment configuration, or vendor default SHALL override any Security Invariant defined in this chapter.

Where conflict exists, the Security Invariant SHALL prevail.

---

## 9.14 Privilege Change Invalidation

Whenever the originating authenticated Human Principal session experiences:

- privilege change,
- role modification,
- clearance modification,
- tenant reassignment,
- session revocation,

previously issued Delegated Credentials SHALL NOT continue to authorize requests beyond their bounded lifetime.

The Authorization Authority SHALL ensure that Delegated Credentials cannot be relied upon as an alternative to current authorization state.

Where immediate revocation is supported, it SHALL be preferred.

Where immediate revocation is unavailable, Delegated Credential lifetime SHALL remain sufficiently bounded to minimize residual authorization risk.

---

# Chapter X — Threat Model

## 10.1 Objective

This chapter identifies the principal security threats addressed by the delegated identity architecture.

Threat analysis is technology-independent and applies regardless of the selected Authorization Authority or delegation technology.

Every identified threat SHALL be mitigated through mandatory architectural controls rather than operational assumptions.

---

## 10.2 Threat — Human Identity Impersonation

### Threat

An attacker attempts to impersonate an authenticated Human Principal.

### Mitigation

- cryptographically verifiable Delegated Credentials;
- authenticated Authorization Authority;
- immutable Human Principal;
- independently validated Delegated Credentials;
- fail-closed delegation.

---

## 10.3 Threat — Acting Service Impersonation

### Threat

An attacker attempts to impersonate the authenticated Studio BFF.

### Mitigation

- confidential-client authentication;
- registered service identity;
- cryptographically verifiable Acting Service identity;
- independent downstream validation.

---

## 10.4 Threat — Over-Privileged Acting Service

### Threat

The authenticated Acting Service possesses privileges exceeding those required for delegated execution, including administrative or impersonation capabilities capable of bypassing delegated identity semantics.

### Mitigation

- least-privilege service accounts;
- confidential-client separation;
- prohibition of administrative impersonation privileges;
- independent authorization validation;
- continuous configuration verification.

The Acting Service SHALL possess only those privileges required to perform delegated execution.

---

## 10.5 Threat — Audience Confusion

### Threat

A Delegated Credential issued for one downstream audience is presented to another downstream service.

### Mitigation

- audience-restricted Delegated Credentials;
- mandatory audience validation;
- prohibition of cross-audience credential reuse.

---

## 10.6 Threat — Privilege Escalation

### Threat

Delegation attempts to increase:

- permissions;
- authorization scope;
- tenant access;
- classification clearance;
- Acting Service authority.

### Mitigation

- mandatory scope reduction;
- immutable tenant identity;
- immutable classification clearance;
- Policy Engine enforcement;
- negative verification testing proving privilege elevation is rejected.

---

## 10.7 Threat — Stale Delegated Credentials

### Threat

Previously issued Delegated Credentials continue to authorize requests after the originating authenticated session has experienced:

- privilege modification;
- role modification;
- tenant reassignment;
- clearance modification;
- session revocation.

### Mitigation

- bounded Delegated Credential lifetime;
- Delegated Credential expiration;
- session-state revalidation where supported;
- immediate revocation where supported.

Delegated Credentials SHALL never become an alternative source of authorization state.

---

## 10.8 Threat — Replay

### Threat

Previously issued Delegated Credentials are replayed by an unauthorized party.

### Mitigation

- bounded credential lifetime;
- credential expiration;
- unique credential identifiers;
- independent signature validation.

---

## 10.9 Threat — Client-Controlled Identity

### Threat

Browser-controlled values attempt to influence delegated identity or authorization.

### Mitigation

- delegated identity originates exclusively from the Authorization Authority;
- browser identity ignored;
- client-controlled headers ignored;
- client-controlled parameters ignored.

---

## 10.10 Threat — Audit Ambiguity

### Threat

Audit records fail to distinguish:

- authenticated Human Principal;
- authenticated Acting Service;
- authorization subject;
- protected resource.

### Mitigation

- independent attribution of the Human Principal;
- independent attribution of Acting Service;
- immutable audit records;
- cryptographically attributable delegated identity.

---

## 10.11 Threat Model Evolution

Future delegation technologies SHALL preserve protection against every threat defined in this chapter.

Additional threats MAY be introduced through future accepted Architecture Decision Records.

Existing threat mitigations SHALL NOT be weakened by implementation-specific optimizations.

---

# Chapter XI — Failure Behaviour

## 11.1 Objective

Failures SHALL preserve security.

Delegation SHALL fail closed.

---

## 11.2 Authorization Authority Unavailable

Delegation SHALL fail.

Protected operations SHALL be denied.

---

## 11.3 Invalid Delegated Credential

The request SHALL be rejected.

---

## 11.4 Expired Delegated Credential

The request SHALL be rejected.

A new Delegated Credential SHALL be obtained.

---

## 11.5 Invalid Audience

The request SHALL be rejected.

---

## 11.6 Invalid Tenant

The request SHALL be rejected.

---

## 11.7 Invalid Clearance

The request SHALL be rejected.

---

## 11.8 Audit Failure

Governed operations SHALL fail closed whenever complete audit attribution cannot be guaranteed.

---

# Chapter XII — Implementation Constraints

## 12.1 General Constraints

Implementation SHALL preserve every architectural invariant defined by this ADR.

---

## 12.2 Platform Independence

Application services SHALL remain independent of delegation technology.

---

## 12.3 Policy Independence

The Policy Engine SHALL remain unchanged.

---

## 12.4 Persistence Independence

Delegation SHALL NOT modify:

- PostgreSQL authority;
- Neo4j projection;
- revision history.

---

## 12.5 Service Independence

Platform services SHALL validate Delegated Credentials independently.

---

## 12.6 Browser Constraints

The Browser SHALL never receive Delegated Credentials.

---

# Chapter XIII — Conformance Requirements

## 13.1 Objective

An implementation conforms to this ADR only if every mandatory architectural requirement defined herein is satisfied.

Conformance SHALL be evaluated against this ADR as a whole rather than against individual implementation technologies.

---

## 13.2 Mandatory Conformance

A conformant implementation SHALL satisfy:

- all Architecture Principles (Chapter III);
- all Trust Boundaries (Chapter IV);
- all Identity Model requirements (Chapter V);
- all Delegation Architecture requirements (Chapter VI);
- all Delegation Credential Requirements (Chapter VII);
- all Authorization and Audit Semantics (Chapter VIII);
- all Security Invariants (Chapter IX);
- all Failure Behaviour requirements (Chapter XI);
- all Implementation Constraints (Chapter XII).

Violation of any mandatory SHALL statement renders an implementation non-conformant.

---

## 13.3 Capability Verification

Prior to implementation, the selected Authorization Authority SHALL successfully demonstrate the complete EMG Delegation Profile.

Capability verification SHALL demonstrate successful conformance with every mandatory requirement defined by the EMG Delegation Profile (Chapter VI), including at minimum:

- preservation of the authenticated Human Principal;
- independently identifiable Acting Service;
- audience restriction;
- scope reduction only;
- tenant integrity;
- classification-clearance integrity;
- confidential-client authentication;
- independent downstream credential validation;
- bounded Delegated Credential lifetime;
- complete audit attribution.

Security-critical properties SHALL be verified through both positive and negative testing.

Negative testing SHALL demonstrate that:

- privilege elevation is rejected;
- audience misuse is rejected;
- tenant substitution is rejected;
- clearance elevation is rejected;
- unauthorized Acting Service impersonation is rejected.

Capability verification SHALL be performed in a dedicated non-production environment.

---

## 13.4 Non-Conformance

Violation of any SHALL statement contained within this ADR SHALL render an implementation non-conformant.

Partial implementation, vendor defaults, or deployment-specific configuration SHALL NOT substitute for conformance.

---

# Chapter XIV — Migration Strategy

## 14.1 Accepted Baseline State

At acceptance, the implemented EMG authentication path authenticated registered Service Principals only.

---

## 14.2 Historical Transitional State

ADR-038 was Accepted before implementation. Acceptance alone did not imply implementation.

Capability verification was mandatory, and Phase 2B remained blocked until it succeeded.

---

## 14.3 Current Verified Implementation State

Capability verification and conformant Phase 2B implementation are complete in
the repository:

- ADR-036 Section 5 remains resolved by this Accepted ADR;
- OAuth 2.0 Token Exchange remains the authoritative delegation architecture;
- delegated human execution is implemented through `apps/studio-bff` and the
  delegated-credential-aware Knowledge Graph boundary.

Production Keycloak values, TLS, secrets, and deployment remain operational
prerequisites and are not implied by repository conformance.

---

# Chapter XV — Capability Verification Criteria and Final Provisions

## 15.1 Capability Verification Criteria

These criteria govern capability verification and implementation readiness. ADR-038 is already **Accepted**; acceptance does not satisfy these criteria or authorize implementation. Phase 2B SHALL NOT begin until every criterion has been satisfied.

### AC-1 — Complete Delegation Profile

The selected Authorization Authority SHALL successfully demonstrate every mandatory capability defined in Chapter VI.

### AC-2 — Human Subject Preservation

Capability verification SHALL demonstrate that the authenticated Human Principal remains unchanged throughout delegated execution.

### AC-3 — Acting Service Identification

Capability verification SHALL demonstrate that the authenticated Acting Service remains independently and cryptographically identifiable.

### AC-4 — Audience Restriction

Capability verification SHALL demonstrate that Delegated Credentials are restricted to exactly one downstream audience.

Cross-audience credential reuse SHALL be rejected.

### AC-5 — Scope Reduction

Capability verification SHALL demonstrate that delegated execution cannot elevate privilege.

Negative testing SHALL prove that privilege escalation attempts are rejected.

### AC-6 — Tenant Integrity

Capability verification SHALL demonstrate that tenant identity remains unchanged throughout delegated execution.

Tenant substitution SHALL be rejected.

### AC-7 — Clearance Integrity

Capability verification SHALL demonstrate that classification-clearance remains unchanged throughout delegated execution.

Clearance elevation SHALL be rejected.

### AC-8 — Confidential Client Authentication

Capability verification SHALL demonstrate that Delegated Credentials are issued only to authenticated confidential clients.

### AC-9 — Independent Downstream Validation

Capability verification SHALL demonstrate that downstream Platform Services independently validate Delegated Credentials before authorization evaluation.

### AC-10 — Bounded Credential Lifetime

Capability verification SHALL demonstrate that Delegated Credentials possess an independently bounded lifetime and automatically expire.

### AC-11 — Audit Completeness

Capability verification SHALL demonstrate complete attribution of:

- authenticated Human Principal;
- authenticated Acting Service;
- authorization decision;
- protected resource;
- tenant;
- classification;
- correlation identifier.

### AC-12 — Security Invariants

Capability verification SHALL demonstrate conformance with every Security Invariant defined in Chapter IX.

### AC-13 — Failure Behaviour

Capability verification SHALL demonstrate fail-closed behaviour for every mandatory failure condition defined in Chapter XI.

### AC-14 — Non-Production Verification

All capability verification SHALL be completed in a dedicated non-production environment.

### AC-15 — Governance Approval

Formal governance confirmation of capability verification SHALL occur before implementation begins and only after successful completion of every preceding capability verification criterion.

---

## 15.2 Relationship to Existing ADRs

ADR-035 continues to govern Human Principal Authentication.

ADR-036 continues to govern the Browser-to-BFF architectural boundary.

Acceptance of this ADR resolves the open delegation sub-decision recorded in ADR-036 Section 5.

ADR-038 is the authoritative specification governing delegated human identity beyond the BFF boundary.

---

## 15.3 Future Evolution

Future delegation technologies MAY replace OAuth 2.0 Token Exchange only through a future accepted Architecture Decision Record.

Any future delegation mechanism SHALL preserve every architectural principle, trust boundary, identity requirement, credential requirement, authorization semantic, audit semantic, security invariant, implementation constraint, and capability verification criterion defined by this ADR.

---

## 15.4 Final Authority

This Accepted ADR is the sole authoritative architectural specification governing delegated human identity throughout the Enterprise Memory Graph (EMG) platform.

Any implementation inconsistent with this ADR SHALL be considered architecturally non-conformant.

---

# Appendix A — Terminology

| Term | Definition |
|------|------------|
| Human Principal | Authenticated human user. |
| Service Principal | Authenticated machine identity. |
| Delegated Principal | Human executing through an authenticated Service Principal. |
| Acting Service | The authenticated BFF performing delegated execution. |
| Authorization Authority | The only authority permitted to issue Delegated Credentials. |
| Delegated Credential | Credential representing delegated execution. |
| Delegated Execution Context | Defined in Chapter V. |

---

# Ratification

This ADR was reviewed by the EMG Architecture Review Board.

Review Outcome:

**Accepted**

No blocking architectural issues were identified.

Acceptance recorded the architecture decision and did not itself imply
implementation. This ADR remains the authoritative specification governing
delegated human identity and resolves ADR-036's former open sub-decision. The
mandatory capability verification and Phase 2B implementation subsequently
completed without weakening its invariants; target-environment configuration
and deployment remain operational prerequisites.
