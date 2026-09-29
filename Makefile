.PHONY: run update-pot update-translations translations build-deb clean

run: translations
	SYSTEMD_RESOLVED_GUI_LOCALE_DIR="$(CURDIR)/build/locale" \
	PYTHONPATH="$(CURDIR)/src" python3 -m systemd_resolved_gui

update-pot:
	xgettext --language=Python --from-code=UTF-8 --keyword=_ \
		--files-from=po/POTFILES.in \
		--output=po/systemd-resolved-gui.pot

update-translations: update-pot
	for catalog in po/*.po; do \
		msgmerge --update --backup=none "$$catalog" po/systemd-resolved-gui.pot; \
	done

translations:
	set -eu; \
	for catalog in po/*.po; do \
		language=$$(basename "$$catalog" .po); \
		locale_dir="build/locale/$$language/LC_MESSAGES"; \
		mkdir -p "$$locale_dir"; \
		msgfmt --check --check-format \
			--output-file="$$locale_dir/systemd-resolved-gui.mo" "$$catalog"; \
	done

build-deb:
	./scripts/build-deb.sh

clean:
	rm -rf build