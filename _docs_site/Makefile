.PHONY: docs docs-serve docs-build css vendor deploy check-cdn clean help

NPM ?= npm

# Rake handles env-var setup (JEKYLL_ENV=production) inside Ruby, which is
# portable across cmd.exe, PowerShell, and POSIX shells. Make's `VAR=value cmd`
# prefix syntax is a bash extension and breaks under cmd.exe on Windows.
# CSS + vendor bundles run via Node (Dart Sass + esbuild) so the entire
# build chain needs zero Ruby native extensions.
RAKE = bundle exec rake

help:
	@echo "Targets:"
	@echo "  make docs         Install Ruby + Node dependencies (one-time)."
	@echo "  make docs-serve   Run Jekyll locally with livereload."
	@echo "  make docs-build   Build CSS + vendor JS + Jekyll site into _site/."
	@echo "  make css          Compile assets/css/main.scss -> main.css (Dart Sass)."
	@echo "  make vendor       Bundle JS modules into assets/vendor/ (no CDN)."
	@echo "  make deploy       Copy _site/ -> site/ for Pages upload."
	@echo "  make check-cdn    Fail if site/ contains any https:// script/link."
	@echo "  make clean        Remove _site/, site/, Jekyll caches, generated CSS."

docs:
	bundle install
	$(NPM) install

docs-serve:
	$(RAKE) serve:livereload

# Order matters: CSS and vendor JS are inputs to Jekyll's static-file copy,
# so they must exist before `jekyll build` runs. (Jekyll does not compile
# Sass itself — see the comment in _config.yml.)
docs-build: css vendor
	$(RAKE) build:strict

css:
	$(NPM) run css

vendor:
	$(NPM) run vendor

deploy: docs-build
	@node scripts/copy-site.mjs

check-cdn:
	@node scripts/check-no-cdn.mjs site

clean:
	$(NPM) run clean
	$(RAKE) clean