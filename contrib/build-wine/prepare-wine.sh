#!/bin/bash

# Please update these carefully, some versions won't work under Wine
NSIS_FILENAME=nsis-3.05-setup.exe
NSIS_URL=https://downloads.sourceforge.net/project/nsis/NSIS%203/3.05/$NSIS_FILENAME
NSIS_SHA256=1a3cc9401667547b9b9327a177b13485f7c59c2303d4b6183e7bc9e6c8d6bfdb


ZBAR_FILENAME=zbarw-20121031-setup.exe
ZBAR_URL=https://sourceforge.net/projects/zbarw/files/$ZBAR_FILENAME/download
ZBAR_SHA256=177e32b272fa76528a3af486b74e9cb356707be1c5ace4ed3fcee9723e2c2c02

LIBUSB_FILENAME=libusb-1.0.22.7z
LIBUSB_URL=https://prdownloads.sourceforge.net/project/libusb/libusb-1.0/libusb-1.0.22/$LIBUSB_FILENAME?download
LIBUSB_SHA256=671f1a420757b4480e7fadc8313d6fb3cbb75ca00934c417c1efa6e77fb8779b

PYINSTALLER_REPO="https://github.com/SomberNight/pyinstaller.git"
PYINSTALLER_COMMIT="31fda9dc83feb1b3f2ff08c89ff7ae61506fc1ca"
# ^ tag 4.1, plus a custom commit that fixes cross-compilation with MinGW

PYTHON_VERSION=3.7.9

## These settings probably don't need change
export WINEPREFIX=/opt/wine64
export WINEDEBUG=-all

PYTHON_FOLDER="python3"
PYHOME="c:/$PYTHON_FOLDER"
PYTHON="wine $PYHOME/python.exe -OO -B"


# Let's begin!
set -e

here="$(dirname "$(readlink -e "$0")")"

. "$CONTRIB"/build_tools_util.sh

info "Booting wine."
wine 'wineboot'


cd "$CACHEDIR"

info "Installing Python."
# note: you might need "sudo apt-get install dirmngr" for the following
# keys from https://www.python.org/downloads/#pubkeys
KEYRING_PYTHON_DEV="keyring-electrum-build-python-dev.gpg"
gpg --no-default-keyring --keyring $KEYRING_PYTHON_DEV --import "$here"/gpg_keys/7ED10B6531D7C8E1BC296021FC624643487034E5.asc
PYTHON_DOWNLOADS="$CACHEDIR/python$PYTHON_VERSION"
mkdir -p "$PYTHON_DOWNLOADS"
for msifile in core dev exe lib pip tools; do
    echo "Installing $msifile..."
    download_if_not_exist "$PYTHON_DOWNLOADS/${msifile}.msi" "https://www.python.org/ftp/python/$PYTHON_VERSION/win32/${msifile}.msi"
    download_if_not_exist "$PYTHON_DOWNLOADS/${msifile}.msi.asc" "https://www.python.org/ftp/python/$PYTHON_VERSION/win32/${msifile}.msi.asc"
    verify_signature "$PYTHON_DOWNLOADS/${msifile}.msi.asc" $KEYRING_PYTHON_DEV
    wine msiexec /i "$PYTHON_DOWNLOADS/${msifile}.msi" /qb TARGETDIR=$PYHOME
done

break_legacy_easy_install

info "Installing build dependencies."
$PYTHON -m pip install --no-dependencies --no-warn-script-location -r "$CONTRIB"/deterministic-build/requirements-wine-build.txt

info "Installing dependencies specific to binaries."
$PYTHON -m pip install --no-dependencies --no-warn-script-location -r "$CONTRIB"/deterministic-build/requirements-binaries.txt

info "Installing ZBar."
download_if_not_exist "$CACHEDIR/$ZBAR_FILENAME" "$ZBAR_URL"
verify_hash "$CACHEDIR/$ZBAR_FILENAME" "$ZBAR_SHA256"
wine "$CACHEDIR/$ZBAR_FILENAME" /S

info "Installing NSIS."
download_if_not_exist "$CACHEDIR/$NSIS_FILENAME" "$NSIS_URL"
verify_hash "$CACHEDIR/$NSIS_FILENAME" "$NSIS_SHA256"
wine "$CACHEDIR/$NSIS_FILENAME" /S

info "Installing libusb."
download_if_not_exist "$CACHEDIR/$LIBUSB_FILENAME" "$LIBUSB_URL"
verify_hash "$CACHEDIR/$LIBUSB_FILENAME" "$LIBUSB_SHA256"
7z x -olibusb "$CACHEDIR/$LIBUSB_FILENAME" -aoa
cp libusb/MS32/dll/libusb-1.0.dll $WINEPREFIX/drive_c/$PYTHON_FOLDER/

mkdir -p $WINEPREFIX/drive_c/tmp
cp "$PROJECT_ROOT/electrum/libsecp256k1-0.dll" $WINEPREFIX/drive_c/tmp/ || fail "Could not copy libsecp to its destination"


info "Building PyInstaller."
# we build our own PyInstaller boot loader as the default one has high
# anti-virus false positives
(
    cd "$WINEPREFIX/drive_c/electrum"
    ELECTRUM_COMMIT_HASH=$(git rev-parse HEAD)
    cd "$CACHEDIR"
    rm -rf pyinstaller
    mkdir pyinstaller
    cd pyinstaller
    # Shallow clone
    git init
    git remote add origin $PYINSTALLER_REPO
    git fetch --depth 1 origin $PYINSTALLER_COMMIT
    git checkout -b pinned "${PYINSTALLER_COMMIT}^{commit}"
    rm -fv PyInstaller/bootloader/Windows-*/run*.exe || true
    # add reproducible randomness. this ensures we build a different bootloader for each commit.
    # if we built the same one for all releases, that might also get anti-virus false positives
    echo "const char *electrum_tag = \"tagged by Electrum@$ELECTRUM_COMMIT_HASH\";" >> ./bootloader/src/pyi_main.c
    pushd bootloader
    # cross-compile to Windows using host python
    python3 ./waf all CC="${GCC_TRIPLET_HOST}-gcc" \
                                              CFLAGS="-static \
                                                      -Wno-dangling-else \
                                                      -Wno-error=unused-value \
                                                      -Wno-error=implicit-function-declaration \
                                                      -Wno-error=int-to-pointer-cast"
    popd
 # sanity check bootloader is there:
    if [ "$GCC_TRIPLET_HOST" = "i686-w64-mingw32" ] ; then
        [[ -e PyInstaller/bootloader/Windows-32bit/runw.exe ]] || fail "Could not find runw.exe in target dir! (32bit)"
    elif [ "$GCC_TRIPLET_HOST" = "x86_64-w64-mingw32" ] ; then
        [[ -e PyInstaller/bootloader/Windows-64bit/runw.exe ]] || fail "Could not find runw.exe in target dir! (64bit)"
    else
        fail "unexpected GCC_TRIPLET_HOST: $GCC_TRIPLET_HOST"
    fi
) || fail "PyInstaller build failed"
info "Installing PyInstaller."
$PYTHON -m pip install --no-dependencies --no-warn-script-location ./pyinstaller

info "Wine is configured."
