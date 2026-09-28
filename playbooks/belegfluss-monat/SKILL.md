---
name: belegfluss-monat
description: Close one month of receipt coverage — statements in, receipts extracted and matched, the upload batch and card breakouts written, the batch marked uploaded, the coverage report
tags: [belegfluss, receipts, datev, coverage, bookkeeping]
allowed-tools: [bf-parse, bf-intake, bf-receipt, bf-match, bf-route, bf-batch, bf-mark, bf-report]
status: draft
---

## Steps

1. bf-parse   in: {statement: raw}        out: Transactions
2. bf-intake  in: {upload_set: raw}       out: Markdown
3. bf-receipt in: {markdown: s2/out}      out: Invoice
4. bf-match   in: {transactions: s1/out}  out: Transactions
5. bf-route   in: {invoice: s3/out}       out: Invoice
6. bf-batch   in: {period: raw}           out: File
7. bf-mark    in: {batch: s6/out}         out: Text
8. bf-report  in: {transactions: s4/out}  out: File

## What this is

The belegfluss month: `bf confirm` repairs drafts between steps 3 and 4, `bf match --list` / `--accept`
settles proposals between 4 and 5. Upload the files step 6 printed, then run step 7 with its batch id.
