# Infrastructure as code

Everything PRAETOR runs on in Google Cloud, described here rather than in a shell history.

**This has not been applied over the running system, and that is deliberate.** The live
project was built by hand while the pipeline was being figured out. Applying a fresh
Terraform state on top of it would try to *create* resources that already exist, and the
first thing that would break is the live queue. So the code is written, validated, and
carries `import` blocks that adopt what is already there.

    make tf-check      # init + validate + fmt, no credentials needed
    make tf-plan       # what it would change, against the real project — read only
    terraform apply    # not run by any make target, on purpose

Run `make tf-plan` and read it before ever applying. A plan that says *create* where you
expected *import* means an import block is missing, and applying it would duplicate a
live resource.

## Staging and production are the same code

`var.environment` is the only difference. It suffixes every resource name and selects the
Cloud Run scaling, so `staging` and `production` cannot drift into different shapes —
which is the failure a hand-built staging environment always eventually has, where the
thing you tested is not the thing you shipped.

Production is the environment that exists today. Staging has **not** been created: it
would cost money at rest (Firestore, Storage and Artifact Registry all bill when idle,
per `docs/` and the teardown note) and the credits are finite. The code is here so that
creating it is one command rather than an afternoon.

## What is deliberately NOT in here

**The billing account, the budgets and the spend caps.** Those are the controls that stop
this project spending money, and a Terraform run that can edit them is a Terraform run
that can remove them. They stay console-only and hand-made.

**The Gemini API key project.** `gen-lang-client-0515700308` must stay billing-disabled,
and the surest way to keep that true is for no automation to have an opinion about it.
