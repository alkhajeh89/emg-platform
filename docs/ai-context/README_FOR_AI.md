{\rtf1\ansi\ansicpg1252\cocoartf2870
\cocoatextscaling0\cocoaplatform0{\fonttbl\f0\fswiss\fcharset0 Helvetica;}
{\colortbl;\red255\green255\blue255;}
{\*\expandedcolortbl;;}
\paperw11900\paperh16840\margl1440\margr1440\vieww11520\viewh8400\viewkind0
\pard\tx566\tx1133\tx1700\tx2267\tx2834\tx3401\tx3968\tx4535\tx5102\tx5669\tx6236\tx6803\pardirnatural\partightenfactor0

\f0\fs24 \cf0 # EMG\'99 \'97 AI Engineering Context\
## Master Context for AI Assistants\
\
Version: 1.0\
Status: Authoritative AI Context\
Audience:\
- Gemini\
- ChatGPT\
- Claude\
- GitHub Copilot\
- Cursor\
- Windsurf\
- Any AI Engineering Assistant\
\
---\
\
# Purpose\
\
This document provides the mandatory context that every AI assistant must load before performing any engineering task within the EMG\'99 repository.\
\
Its purpose is to ensure every generated artifact remains fully aligned with the approved architecture and engineering standards.\
\
This document is NOT architecture.\
\
It is the navigation guide to the architecture.\
\
---\
\
# Project Identity\
\
Project Name\
\
Enterprise Memory Graph (EMG\'99)\
\
Current Product Positioning\
\
Enterprise Intelligence Platform\
\
Mission\
\
Every organization deserves a memory.\
\
EMG is a sovereign Enterprise Intelligence Platform capable of:\
\
\'95 Institutional Memory\
\'95 Knowledge Graph\
\'95 Enterprise AI\
\'95 Decision Intelligence\
\'95 Decision Replay\
\'95 Investigation\
\'95 Digital Twins\
\'95 Predictive Intelligence\
\'95 Enterprise Search\
\'95 Enterprise Copilot\
\'95 Enterprise Governance\
\
The platform is designed primarily for:\
\
- Government\
- Defense\
- Aviation\
- Critical Infrastructure\
- National Security\
- Large Enterprises\
\
---\
\
# Engineering Philosophy\
\
The platform follows several immutable principles.\
\
## 1.\
\
Architecture before code.\
\
Implementation never changes architecture.\
\
---\
\
## 2.\
\
Every architectural decision must already exist inside the Architecture documentation.\
\
If something is missing:\
\
Create an ADR.\
\
Never invent architecture.\
\
---\
\
## 3.\
\
Backend is Domain Driven Design.\
\
Every service is:\
\
- independent\
- bounded\
- loosely coupled\
\
---\
\
## 4.\
\
Frontend is Enterprise UX.\
\
Never design consumer-style interfaces.\
\
The platform is an operational intelligence system.\
\
---\
\
## 5.\
\
Security is never optional.\
\
Every component assumes Zero Trust.\
\
---\
\
## 6.\
\
Every decision must be explainable.\
\
Every AI answer must have provenance.\
\
---\
\
# Repository Structure\
\
The repository is organized into several logical domains.\
\
docs/\
Architecture\
Engineering\
Enterprise Design\
Phases\
Product\
Sprints\
AI Context\
\
libs/\
\
Shared reusable libraries.\
\
services/\
\
Business services.\
\
apps/\
\
Frontend applications.\
\
infra/\
\
Infrastructure.\
\
tools/\
\
Developer tooling.\
\
observability/\
\
Dashboards and monitoring.\
\
---\
\
# Source of Truth\
\
The following documents are authoritative.\
\
Product\
\
docs/product/\
\
EMG_PRODUCT_VISION.md\
\
EMG_PRODUCT_ARCHITECTURE_FREEZE.md\
\
Architecture\
\
docs/architecture/\
\
EMG_Architecture_Baseline_v1.0_Final.md\
\
ADR-014\
\
ADR-015\
\
ADR-016\
\
ADR-017\
\
Engineering\
\
docs/engineering/\
\
platform-foundation-architecture.md\
\
memory-graph-architecture.md\
\
memory-graph-data-model.md\
\
memory-graph-api.md\
\
storage-ports.md\
\
testing-strategy.md\
\
definition-of-done.md\
\
Enterprise UX\
\
docs/enterprise-design/\
\
UX_OVERVIEW.md\
\
DESIGN_SYSTEM.md\
\
SCREEN_SPECIFICATIONS.md\
\
FRONTEND_ARCHITECTURE.md\
\
These documents override any assumptions.\
\
---\
\
# AI Rules\
\
The AI assistant MUST\
\
\uc0\u10003  Read architecture before implementation.\
\
\uc0\u10003  Preserve architecture.\
\
\uc0\u10003  Respect ADR decisions.\
\
\uc0\u10003  Follow coding standards.\
\
\uc0\u10003  Produce production-quality code.\
\
\uc0\u10003  Preserve DDD boundaries.\
\
\uc0\u10003  Preserve Clean Architecture.\
\
\uc0\u10003  Respect Zero Trust.\
\
\uc0\u10003  Produce testable code.\
\
\uc0\u10003  Follow repository conventions.\
\
---\
\
The AI assistant MUST NOT\
\
\uc0\u10007  Invent new architecture.\
\
\uc0\u10007  Move business logic into UI.\
\
\uc0\u10007  Bypass APIs.\
\
\uc0\u10007  Create hidden dependencies.\
\
\uc0\u10007  Ignore ADRs.\
\
\uc0\u10007  Ignore security.\
\
\uc0\u10007  Break module boundaries.\
\
\uc0\u10007  Introduce temporary hacks.\
\
\uc0\u10007  Produce placeholder implementations.\
\
\uc0\u10007  Generate unfinished code.\
\
---\
\
# Coding Quality\
\
All generated code must satisfy:\
\
Production Ready\
\
mypy strict\
\
ruff clean\
\
black clean\
\
pytest passing\
\
No TODOs\
\
No FIXME\
\
No XXX\
\
No placeholders\
\
No mock implementations\
\
---\
\
# Frontend Rules\
\
Technology\
\
React\
\
TypeScript\
\
Next.js\
\
TailwindCSS\
\
shadcn/ui\
\
React Flow\
\
Enterprise Design System\
\
Every screen must follow\
\
UX_OVERVIEW\
\
SCREEN_SPECIFICATIONS\
\
DESIGN_SYSTEM\
\
FRONTEND_ARCHITECTURE\
\
No custom visual language outside the design system.\
\
---\
\
# Backend Rules\
\
Architecture\
\
DDD\
\
Hexagonal\
\
Ports & Adapters\
\
Event Driven\
\
CQRS where specified\
\
No shared database ownership.\
\
Every service owns its data.\
\
---\
\
# Database Rules\
\
PostgreSQL\
\
Single Source of Truth\
\
Neo4j\
\
Projection only\
\
Never authoritative.\
\
Projection must always be rebuildable.\
\
---\
\
# Security Rules\
\
Zero Trust\
\
ABAC\
\
RBAC\
\
Audit Everything\
\
Immutable Logs\
\
Explainable AI\
\
Human in the Loop\
\
Least Privilege\
\
---\
\
# AI Features\
\
Grounded Retrieval\
\
Knowledge Graph\
\
Decision Replay\
\
Enterprise Search\
\
Executive Copilot\
\
Investigation\
\
Simulation\
\
Prediction\
\
Digital Twins\
\
Every AI output requires provenance.\
\
---\
\
# Testing\
\
Every implementation requires\
\
Unit Tests\
\
Integration Tests\
\
Contract Tests\
\
Architecture Tests\
\
Performance Validation\
\
Security Validation\
\
---\
\
# Sprint Workflow\
\
Every Sprint follows\
\
Design\
\
\uc0\u8595 \
\
Architecture Review\
\
\uc0\u8595 \
\
Approval\
\
\uc0\u8595 \
\
Implementation\
\
\uc0\u8595 \
\
Testing\
\
\uc0\u8595 \
\
Review\
\
\uc0\u8595 \
\
Merge\
\
Never skip Design.\
\
---\
\
# When Working on a Sprint\
\
The AI assistant should only read\
\
Current Sprint Design\
\
Relevant ADRs\
\
Relevant Architecture\
\
Relevant Engineering Documents\
\
Do not load every Sprint.\
\
---\
\
# Missing Information\
\
If the required architecture is not documented:\
\
Stop.\
\
Ask for clarification.\
\
Never invent missing architecture.\
\
---\
\
# Definition of Success\
\
A generated solution is considered successful only when:\
\
Architecture preserved\
\
Coding standards satisfied\
\
Security preserved\
\
DDD preserved\
\
Tests passing\
\
No technical debt introduced\
\
Repository conventions followed\
\
Documentation updated where required\
\
---\
\
End of Document}
