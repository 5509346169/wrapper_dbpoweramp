.PHONY: docs docs-serve docs-build vendor deploy check-cdn clean help

BUNDLE ?= bundle exec jekyll
NPM    ?= npm

help:
	@echo "Targets:"
	@echo "  make docs         Install Ruby + Node dependencies (one-time)."
	@echo "  make docs-serve   Run Jekyll locally with livereload."
	@echo "  make docs-build   Build the site into _site/ with strict_front_matter."
	@echo "  make vendor       Bundle JS modules into assets/vendor/ (no CDN)."
	@echo "  make deploy       Copy _site/ -> site/ for Pages upload."
	@echo "  make check-cdn    Fail if site/ contains any https:// script/link."
	@echo "  make clean        Remove _site/, site/, Jekyll caches."

docs:
	$(BUNDLE) install
	$(NPM) install

docs-serve:
	$(BUNDLE) serve --livereload --incremental --host 127.0.0.1 --port 4000

docs-build:
	JEKYLL_ENV=production $(BUNDLE) build --trace --strict_front_matter

vendor:
	$(NPM) run vendor

deploy: docs-build vendor
	@node scripts/copy-site.mjs

check-cdn:
	@node scripts/check-no-cdn.mjs site

clean:
	rm -rf _site site .jekyll-cache .jekyll-metadata
