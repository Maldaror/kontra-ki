VENV := .venv
PYTHON := $(VENV)/bin/python

.PHONY: install up down test clean

install: $(VENV)/bin/activate

$(VENV)/bin/activate: pyproject.toml
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -e ".[dev]"
	touch $(VENV)/bin/activate

up: install
	claude mcp add kontra-ki --scope user -- $(CURDIR)/$(PYTHON) -m kontra_ki.server

down:
	-claude mcp remove kontra-ki

test: install
	$(PYTHON) -m pytest tests/ -v

clean: down
	rm -rf $(VENV) .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
