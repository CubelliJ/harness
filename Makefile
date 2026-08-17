.PHONY: run configure test install install-user uninstall

PYTHON ?= python3
HARNESS_HOME ?= $(HOME)/.harness
VENV ?= $(HARNESS_HOME)/venv
BIN ?= $(HOME)/.local/bin

run:
	$(PYTHON) -m harness

configure:
	$(PYTHON) -m harness configure

test:
	$(PYTHON) -m unittest discover -s tests -v

# Use a private environment so Homebrew/macOS PEP 668 restrictions are avoided.
# The user never needs to activate it; the launcher points directly to it.
install install-user:
	$(PYTHON) -m venv "$(VENV)"
	"$(VENV)/bin/python" -m pip install --upgrade pip
	"$(VENV)/bin/python" -m pip install .
	@mkdir -p "$(BIN)"
	@ln -sfn "$(VENV)/bin/harness" "$(BIN)/harness"
	@startup="$(HOME)/.zshrc"; \
	if [ -n "$$SHELL" ] && echo "$$SHELL" | grep -q '/bash$$'; then startup="$(HOME)/.bashrc"; fi; \
	if ! grep -Fqx 'export PATH="$$HOME/.local/bin:$$PATH"' "$$startup" 2>/dev/null; then \
		echo '' >> "$$startup"; echo '# Harness' >> "$$startup"; echo 'export PATH="$$HOME/.local/bin:$$PATH"' >> "$$startup"; \
	fi; \
	echo "Installed harness. Run: source $$startup"

uninstall:
	@rm -f "$(BIN)/harness"
	@rm -rf "$(VENV)"
	@echo "Uninstalled harness"
