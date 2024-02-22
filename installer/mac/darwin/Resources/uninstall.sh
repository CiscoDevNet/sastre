#!/bin/bash

#Parameters
DATE=`date +%Y-%m-%d`
TIME=`date +%H:%M:%S`
LOG_PREFIX="[$DATE $TIME]"

#Functions
log_info() {
    echo "${LOG_PREFIX}[INFO]" $1
}

log_warn() {
    echo "${LOG_PREFIX}[WARN]" $1
}

log_error() {
    echo "${LOG_PREFIX}[ERROR]" $1
}

#Check running user
if (( $EUID != 0 )); then
    echo "Please run as root."
    exit
fi

echo "Welcome to Sastre-Pro application uninstaller"
echo "The following docker image will be REMOVED:"
echo "  sastre-pro:latest"
while true; do
    read -p "Do you wish to continue [Y/n]?" answer
    [[ $answer == "y" || $answer == "Y" || $answer == "" ]] && break
    [[ $answer == "n" || $answer == "N" ]] && exit 0
    echo "Please answer with 'y' or 'n'"
done

echo "=============Sastre-Pro application uninstalling process started============="

[ -e ~/sastre-pro/sastre-pro.sh ] && rm -rf ~/sastre-pro/sastre-pro.sh
if [ $? -eq 0 ]
then
  echo "[1/3] [DONE] Successfully deleted sastre-pro launch script"
else
  echo "[1/3] [ERROR] Could not delete sastre-pro launch script" >&2
fi

[ -e ~/sastre-pro/uninstall.sh ] && rm -rf ~/sastre-pro/uninstall.sh
if [ $? -eq 0 ]
then
  echo "[2/3] [DONE] Successfully deleted sastre-pro uninstall script"
else
  echo "[2/3] [ERROR] Could not delete sastre-pro uninstall script" >&2
fi

#remove sastre-pro containers and images
list_existing_sastre_images=$(docker images --filter=reference="sastre-pro:latest" -q)
# Sleep interval in seconds
SLEEP_INTERVAL=5

function are_containers_stopped() {
    local containers
    containers=$(docker ps -q --filter "ancestor=sastre-pro:latest")
    [[ -z "$containers" ]]
}

# Function to check if the list of containers is empty
function are_containers_removed() {
    local containers
    containers=$(docker ps -aq --filter "ancestor=sastre-pro:latest")
    [[ -z "$containers" ]]
}

if [ -z "$list_existing_sastre_images" ]; then
    echo "[3/3] [DONE] No sastre-pro:latest image(s) found."
else
    echo "sastre-pro:latest image(s) found, going to delete sastre containers if any"
    docker stop $(docker ps -q --filter "ancestor=sastre-pro:latest")
    while ! are_containers_stopped; do
      echo "Waiting for containers to stop..."
      sleep "$SLEEP_INTERVAL"
    done
    docker rm $(docker ps -aq --filter "ancestor=sastre-pro:latest")
    
    while ! are_containers_removed; do
      echo "Waiting for containers to be removed..."
      sleep "$SLEEP_INTERVAL"
    done

    for image_id in $list_existing_sastre_images; do
        echo "Deleting sastre-pro image: $image_id"
        docker rmi -f "$image_id"
    done
    echo "[3/3] [DONE] Successfully deleted latest sastre-pro docker image"
fi


echo "=============Sastre-Pro application uninstall process finished============="
echo "NOTE: Please delete ~/sastre-pro/sastre-volume folder manually (if you choose so)"
exit 0
