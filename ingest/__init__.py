"""The automation layer. It calls the kernel; the kernel does not know it exists.

Everything under `ingest/` is orchestration: fetching a document, calling Document AI,
handing the result to `praetor/`, writing the outcome where a person will see it. None of
it is security-critical, and none of it may become so.

`tests/test_ingest.py` asserts the direction of that dependency, and asserts that a
document run through the kernel directly and through this package produce the identical
decision -- so "the automation adds nothing and removes nothing" is a test rather than an
intention.
"""
