"""Shared test setup.

The prober now samples randomly (which resumes a single-shot probe hits; which name
each bias swap targets). Seed the stdlib RNG before every test so that sampling is
reproducible in the suite — production runs are unseeded and vary per run.
"""
import random

import pytest


@pytest.fixture(autouse=True)
def _deterministic_random():
    random.seed(1234)
