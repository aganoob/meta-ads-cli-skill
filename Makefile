.PHONY: check test validate

PYTHON ?= python3

check: validate test

validate:
	$(PYTHON) scripts/validate_repo.py

test:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py'
