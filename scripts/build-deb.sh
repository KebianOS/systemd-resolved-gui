#!/bin/sh
set -eu

PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_ROOT"

for tool in dpkg-deb dpkg-parsechangelog msgfmt install; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        printf 'Missing build tool: %s\n' "$tool" >&2
        exit 1
    fi
done

VERSION=$(dpkg-parsechangelog --file debian/changelog --show-field Version)
ARCHITECTURE=$(dpkg --print-architecture)
BUILD_DIR="$PROJECT_ROOT/build"
mkdir -p "$BUILD_DIR"
STAGING=$(mktemp -d "$BUILD_DIR/package.XXXXXX")
trap 'rm -rf "$STAGING"' EXIT HUP INT TERM

PACKAGE_ROOT="$STAGING/systemd-resolved-gui"
install -d \
    "$PACKAGE_ROOT/DEBIAN" \
    "$PACKAGE_ROOT/usr/bin" \
    "$PACKAGE_ROOT/usr/lib/python3/dist-packages/systemd_resolved_gui" \
    "$PACKAGE_ROOT/usr/share/applications" \
    "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps"

for source in src/systemd_resolved_gui/*.py; do
    install -m 0644 "$source" \
        "$PACKAGE_ROOT/usr/lib/python3/dist-packages/systemd_resolved_gui/"
done

install -m 0755 data/systemd-resolved-gui "$PACKAGE_ROOT/usr/bin/"
install -m 0644 data/systemd-resolved-gui.desktop \
    "$PACKAGE_ROOT/usr/share/applications/"
install -m 0644 data/icons/hicolor/scalable/apps/systemd-resolved-gui.svg \
    "$PACKAGE_ROOT/usr/share/icons/hicolor/scalable/apps/"

for catalog in po/*.po; do
    language=${catalog##*/}
    language=${language%.po}
    locale_dir="$PACKAGE_ROOT/usr/share/locale/$language/LC_MESSAGES"
    install -d "$locale_dir"
    msgfmt --check --check-format \
        --output-file="$locale_dir/systemd-resolved-gui.mo" "$catalog"
    chmod 0644 "$locale_dir/systemd-resolved-gui.mo"
done

sed "s/^Version: .*/Version: $VERSION/" debian/control \
    > "$PACKAGE_ROOT/DEBIAN/control"
printf '\n' >> "$PACKAGE_ROOT/DEBIAN/control"
OUTPUT="$BUILD_DIR/systemd-resolved-gui_${VERSION}_${ARCHITECTURE}.deb"
dpkg-deb --root-owner-group --build "$PACKAGE_ROOT" "$OUTPUT"
printf 'Built package: %s\n' "$OUTPUT"