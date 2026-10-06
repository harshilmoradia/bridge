# bridge

> The AI bridge between your bank and your books. Powered by NVIDIA Nemotron on Nebius.

[License: Apache-2.0]

## What it does
Bridge is an AI accounting agent that works through the month instead of
waiting for month-end. It matches bank transactions to bills and invoices,
reconciles corporate card spend, and proposes accruals and prepaid
amortization. Every proposed entry includes its source document,
reasoning, and a confidence score. High-confidence items post
automatically, and the rest go to a human exception queue.

## Why
Month-end close is slow because manual work piles up. Most of it is
repetitive matching and coding that an agent can do as data arrives,
leaving accountants to review exceptions and explain the numbers.

## How it works
1. Bank, bill, invoice and card data comes in.
2. Nemotron models match and classify transactions, routed by difficulty.
3. Entries are proposed with evidence and confidence scores.
4. A human approves exceptions, and entries post to a mock ERP
   with a full audit trail.

## Quick start
    git clone https://github.com/<you>/bridge
    cd bridge
    cp .env.example .env   # add your Nebius API key
    docker compose up

## Repo layout
    frontend/   backend/   docs/

## License
Apache-2.0