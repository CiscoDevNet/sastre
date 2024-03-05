#!/bin/bash

#Configuration Variables and Parameters

#Parameters
SCRIPTPATH="$( cd -- "$(dirname "$0")" >/dev/null 2>&1 ; pwd -P )"
TARGET_DIRECTORY="$SCRIPTPATH/target"
PRODUCT=${1}
VERSION=${2}
DATE=`date +%Y-%m-%d`
TIME=`date +%H:%M:%S`
LOG_PREFIX="[$DATE $TIME]"
PWD_HOME="/tmp"

function printSignature() {
  cat "$SCRIPTPATH/utils/ascii_art.txt"
  echo
}

function printUsage() {
  echo -e "\033[1mUsage:\033[0m"
  echo "$0 [APPLICATION_NAME] [APPLICATION_VERSION]"
  echo
  echo -e "\033[1mOptions:\033[0m"
  echo "  -h (--help)"
  echo
  echo -e "\033[1mExample::\033[0m"
  echo "$0 wso2am 2.6.0"
}

#Start the generator
printSignature

#Argument validation
if [[ "$1" == "-h" ||  "$1" == "--help" ]]; then
    printUsage
    exit 1
fi
if [ -z "$1" ]; then
    echo "Please enter a valid application name for your application"
    echo
    printUsage
    exit 1
else
    echo "Application Name : $1"
fi


#Functions
go_to_dir() {
    pushd $1 >/dev/null 2>&1
}

log_info() {
    echo "${LOG_PREFIX}[INFO]" $1
}

log_warn() {
    echo "${LOG_PREFIX}[WARN]" $1
}

log_error() {
    echo "${LOG_PREFIX}[ERROR]" $1
}

deleteInstallationDirectory() {
    log_info "Cleaning $TARGET_DIRECTORY directory."
    rm -rf "$TARGET_DIRECTORY"

    if [[ $? != 0 ]]; then
        log_error "Failed to clean $TARGET_DIRECTORY directory" $?
        exit 1
    fi
}

createInstallationDirectory() {
    if [ -d "${TARGET_DIRECTORY}" ]; then
        deleteInstallationDirectory
    fi
    mkdir -pv "$TARGET_DIRECTORY"

    if [[ $? != 0 ]]; then
        log_error "Failed to create $TARGET_DIRECTORY directory" $?
        exit 1
    fi
}

copyDarwinDirectory(){
  createInstallationDirectory
  cp -r "$SCRIPTPATH/darwin" "${TARGET_DIRECTORY}/"
  chmod -R 755 "${TARGET_DIRECTORY}/darwin/scripts"
  chmod -R 755 "${TARGET_DIRECTORY}/darwin/Resources"
  chmod 755 "${TARGET_DIRECTORY}/darwin/Distribution"
}

copyBuildDirectory() {
    sed -i '' -e 's/__VERSION__/'${VERSION}'/g' "${TARGET_DIRECTORY}/darwin/scripts/postinstall"
    sed -i '' -e 's/__PRODUCT__/'${PRODUCT}'/g' "${TARGET_DIRECTORY}/darwin/scripts/postinstall"
    chmod -R 755 "${TARGET_DIRECTORY}/darwin/scripts/postinstall"
    cp -a "$SCRIPTPATH"/application/container_engine.sh "${TARGET_DIRECTORY}/darwin/scripts/"

    sed -i '' -e 's/__VERSION__/'${VERSION}'/g' "${TARGET_DIRECTORY}/darwin/Distribution"
    sed -i '' -e 's/__PRODUCT__/'${PRODUCT}'/g' "${TARGET_DIRECTORY}/darwin/Distribution"
    chmod -R 755 "${TARGET_DIRECTORY}/darwin/Distribution"

    sed -i '' -e 's/__VERSION__/'${VERSION}'/g' "${TARGET_DIRECTORY}"/darwin/Resources/*.html
    sed -i '' -e 's/__PRODUCT__/'${PRODUCT}'/g' "${TARGET_DIRECTORY}"/darwin/Resources/*.html
    chmod -R 755 "${TARGET_DIRECTORY}/darwin/Resources/"

    rm -rf "${TARGET_DIRECTORY}/darwinpkg"
    mkdir -p "${TARGET_DIRECTORY}/darwinpkg"

    #Copy cellery product to /Library/Cellery
    mkdir -p "${TARGET_DIRECTORY}"/darwinpkg/"${PWD_HOME}"/${PRODUCT}
    cp -a "$SCRIPTPATH"/application/. "${TARGET_DIRECTORY}"/darwinpkg/"${PWD_HOME}"/${PRODUCT}
    chmod -R 755 "${TARGET_DIRECTORY}"/darwinpkg/"${PWD_HOME}"/${PRODUCT}

    rm -rf "${TARGET_DIRECTORY}/package"
    mkdir -p "${TARGET_DIRECTORY}/package"
    chmod -R 755 "${TARGET_DIRECTORY}/package"

    rm -rf "${TARGET_DIRECTORY}/pkg"
    mkdir -p "${TARGET_DIRECTORY}/pkg"
    chmod -R 755 "${TARGET_DIRECTORY}/pkg"
}

function buildPackage() {
    log_info "Application installer package building started.(1/3)"
    pkgbuild --identifier "sastre-pro" \
    --version "${VERSION}" \
    --scripts "${TARGET_DIRECTORY}/darwin/scripts" \
    --root "${TARGET_DIRECTORY}/darwinpkg" \
    "${TARGET_DIRECTORY}/package/sastre-pro.pkg" > /dev/null 2>&1
}

function buildProduct() {
    log_info "Application installer product building started.(2/3)"
    productbuild --distribution "${TARGET_DIRECTORY}/darwin/Distribution" \
    --resources "${TARGET_DIRECTORY}/darwin/Resources" \
    --package-path "${TARGET_DIRECTORY}/package" \
    "${TARGET_DIRECTORY}/pkg/$1" > /dev/null 2>&1
}

function signProduct() {
    log_info "Application installer signing process started.(3/3)"
    mkdir -pv "${TARGET_DIRECTORY}/pkg-signed"
    chmod -R 755 "${TARGET_DIRECTORY}/pkg-signed"

    read -p "Please enter the Apple Developer Installer Certificate ID:" APPLE_DEVELOPER_CERTIFICATE_ID
    productsign --sign "Developer ID Installer: ${APPLE_DEVELOPER_CERTIFICATE_ID}" \
    "${TARGET_DIRECTORY}/pkg/$1" \
    "${TARGET_DIRECTORY}/pkg-signed/$1"

    pkgutil --check-signature "${TARGET_DIRECTORY}/pkg-signed/$1"
}

function createInstaller() {
    log_info "Application installer generation process started.(3 Steps)"
    buildPackage
    #buildProduct ${PRODUCT}-macos-installer-x64-${VERSION}.pkg
    buildProduct sastre-pro.pkg
    while true; do
        read -p "Do you wish to sign the installer (You should have Apple Developer Certificate) [y/N]?" answer
        [[ $answer == "y" || $answer == "Y" ]] && FLAG=true && break
        [[ $answer == "n" || $answer == "N" || $answer == "" ]] && log_info "Skipped signing process." && FLAG=false && break
        echo "Please answer with 'y' or 'n'"
    done
    [[ $FLAG == "true" ]] && signProduct ${PRODUCT}-macos-installer-x64-${VERSION}.pkg
    log_info "Application installer generation steps finished."
}

function createUninstaller(){
    cp -r "$SCRIPTPATH/darwin/Resources/uninstall.app" "${TARGET_DIRECTORY}/darwinpkg/${PWD_HOME}/${PRODUCT}"
    cp -r "$SCRIPTPATH/darwin/Resources/caution.png" "${TARGET_DIRECTORY}/darwinpkg/${PWD_HOME}/${PRODUCT}"
    cp -r "$SCRIPTPATH/darwin/Resources/sastre.icns" "${TARGET_DIRECTORY}/darwinpkg/${PWD_HOME}/${PRODUCT}"
    cp "$SCRIPTPATH/darwin/Resources/uninstall.sh" "${TARGET_DIRECTORY}/darwinpkg/${PWD_HOME}/${PRODUCT}"
    sed -i '' -e "s/__VERSION__/${VERSION}/g" "${TARGET_DIRECTORY}/darwinpkg/${PWD_HOME}/${PRODUCT}/uninstall.sh"
    sed -i '' -e "s/__PRODUCT__/${PRODUCT}/g" "${TARGET_DIRECTORY}/darwinpkg/${PWD_HOME}/${PRODUCT}/uninstall.sh"
}

#Pre-requisites
command -v mvn -v >/dev/null 2>&1 || {
    log_warn "Apache Maven was not found. Please install Maven first."
    # exit 1
}
command -v ballerina >/dev/null 2>&1 || {
    log_warn "Ballerina was not found. Please install ballerina first."
    # exit 1
}

#Main script
log_info "Installer generating process started."

copyDarwinDirectory
copyBuildDirectory
createUninstaller
createInstaller

log_info "Installer generating process finished"
exit 0