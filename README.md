# TaxFlow

TaxFlow is an AI assistant that checks vendor invoices against a company's accounting records. It finds the
matching record, points out anything that doesn't line up, and shows where every number came from. A person
reviews the result and makes the final call.

- Code: https://github.com/alyssaqle/taxflow-reconciliation
- Live demo: coming soon
- Technical details: [TECHNICAL.md](TECHNICAL.md)

## The problem

Before invoices feed into month-end close, tax work, or an audit, someone has to confirm that each invoice
matches how it was recorded in the books. Today that usually means searching a spreadsheet for each invoice,
comparing details by eye, re-adding totals with a calculator, and writing notes by hand.

The work is repetitive, but mistakes are costly. An invoice can be wrong in two separate ways: it can disagree
with the accounting record, or its own math can be off. Look-alike records, such as the same amount with one
digit different in the invoice number, make it easy to approve the wrong match.

## Who it's for

The intended user is a finance or accounting operations analyst who reviews batches of vendor invoices. Their
job is to work out which invoices agree with the records and exactly what is wrong with the rest, so they can
close the review and ask the client or vendor precise questions. Their work gets reviewed too, so they need to
be able to show how they reached each decision.

This user is a hypothesis based on how invoice review generally works. I haven't interviewed analysts yet.

## How TaxFlow solves it

1. The analyst picks an invoice and the accounting records.
2. TaxFlow reads the invoice and pulls out the vendor, invoice number, date, currency, and total. Each value is
   linked to the line it came from.
3. It finds the matching accounting record and compares the two.
4. It shows what matches, what doesn't, and what to ask next.
5. The analyst approves the invoice or flags it for follow-up, and downloads a report.

An example: an invoice lists $800 of services plus $80 tax, but says the total is $950, and the books also
recorded $950. A simple check would call that a match. TaxFlow reports that the books agree with the invoice,
and separately that the invoice's own math should give $880. It won't let the invoice be approved until someone
follows up.

## What I prioritized for the MVP

I ranked risks by what would hurt a reviewer most. Approving something wrong is worst, missing a problem is
next, and being slow is last.

1. Never approve a wrong match. When TaxFlow isn't sure, for example when two records look the same, it asks
   the analyst instead of guessing.
2. Show the evidence. Every number links back to its source, so the analyst can check it in one click instead
   of trusting the tool.
3. Keep a person in charge. TaxFlow prepares the review, and the analyst decides.
4. Measure before claiming anything. I tested the tool on documents it hadn't seen before reporting any
   results.

I also cut scope twice. The first plan covered invoices and two kinds of tax forms. I narrowed it to invoices,
then changed the product from reading single invoices to comparing invoices with accounting records, because
that comparison is the part of the review that actually needs help. PDF uploads, batch processing, and editing
fields in the app were left for later.

## Trade-offs I made

| I chose | Over | Because | The cost |
|---|---|---|---|
| Asking a person when unsure | Always picking a best guess | A wrong match is more expensive than a question | Analysts see more items marked for follow-up |
| Exact matching on invoice number and vendor | Fuzzy matching | Fuzzy matching can link the wrong records | A typo in a vendor name shows up as "no match" |
| AI only for reading invoices, plain code for math and matching | Letting the AI decide matches | Code gives the same answer every time and can be explained | Less flexible with unusual layouts |
| Showing a source for every value | Showing results only | Reviewers need a trail they can defend | More work to build, and values without a verifiable source get flagged |
| Synthetic data only | Real company documents | Safe to share publicly, with no client data | Results don't prove how it works on real invoices |
| A smaller, cheaper AI model | A larger model | Fast and affordable enough to test on 500 documents | I haven't compared it against larger models |

## Tools and why

| Tool | Why I used it |
|---|---|
| Python | Handles exact money math and the matching rules |
| Azure OpenAI | Reads invoices and decides which checks to run; it runs on Microsoft Azure, which many companies already use |
| Streamlit | Turned the Python project into a working web app quickly, with free hosting for a demo |
| GitHub | Version history and a public home for the code |
| Tesseract and the FATURA dataset | A free text-recognition tool and a public set of 10,000 synthetic invoice images, used to test the tool on documents I didn't create |

## Results so far

- On 500 synthetic invoice images it hadn't seen before, TaxFlow read 95.6% of the details correctly, compared
  with 88.3% for a simple rule-based approach. It got every key detail right on 85% of invoices, against 59%
  for the simpler approach. When a detail was missing from an invoice, it never invented one (0 of 197 cases).
- In 3,000 test lookups against generated accounting records of up to 100,000 rows, it found the right record
  or correctly reported a problem every time, with no wrong matches.
- Whether it saves reviewers time is not measured yet. A timing study with real reviewers is ready to run.

All test data is synthetic, so these results show the tool works as designed, not how it performs on real
company documents.

## What's next

- Run the timing study with 3 to 5 reviewers to see whether TaxFlow actually saves time.
- Test on real business documents.
- Support PDF invoices and batches of invoices.
- Let analysts confirm a match themselves when two records look alike, with a record of who decided.

TaxFlow is an independent prototype and is not affiliated with any company. It doesn't file taxes, pay
invoices, or change anyone's accounting records.
