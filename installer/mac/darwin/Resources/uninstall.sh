#!/bin/bash
source ~/sastre-pro/container_engine.sh

if [ -z "${CONTAINER_EXE}" ]; then
    echo "" 
    echo "Podman or Docker container engine is not running. Please ensure either Podman or Docker is installed and running"
    exit 1
fi

echo "Welcome to Sastre-Pro application uninstaller"
echo "The following image will be REMOVED:"
echo "  sastre-pro:latest"
while true; do
    read -p "Do you wish to continue [Y/n]?" answer
    [[ $answer == "y" || $answer == "Y" || $answer == "" ]] && break
    [[ $answer == "n" || $answer == "N" ]] && exit 0
    echo "Please answer with 'y' or 'n'"
done

echo "=============Sastre-Pro application uninstalling process started============="


#remove sastre-pro containers and images
list_existing_sastre_images=$($CONTAINER_EXE images --filter=reference="localhost/sastre-pro:latest" -q)
# Sleep interval in seconds
SLEEP_INTERVAL=0

function are_containers_stopped() {
    local containers
    containers=$($CONTAINER_EXE  ps -q --filter "ancestor=localhost/sastre-pro:latest")
    [[ -z "$containers" ]]
}

# Function to check if the list of containers is empty
function are_containers_removed() {
    local containers
    containers=$($CONTAINER_EXE ps -aq --filter "ancestor=localhost/sastre-pro:latest")
    [[ -z "$containers" ]]
}

if [ -z "$list_existing_sastre_images" ]; then
    echo "[1/3] [DONE] No sastre-pro:latest image(s) found."
else
    echo "sastre-pro:latest image(s) found, going to delete sastre containers if any"
    $CONTAINER_EXE  stop $($CONTAINER_EXE  ps -q --filter "ancestor=localhost/sastre-pro:latest")
    while ! are_containers_stopped; do
      echo "Waiting for containers to stop..."
      sleep "$SLEEP_INTERVAL"
    done
    $CONTAINER_EXE rm $($CONTAINER_EXE ps -aq --filter "ancestor=localhost/sastre-pro:latest")
    
    while ! are_containers_removed; do
      echo "Waiting for containers to be removed..."
      sleep "$SLEEP_INTERVAL"
    done

    for image_id in $list_existing_sastre_images; do
        echo "Deleting sastre-pro image: $image_id"
        $CONTAINER_EXE rmi -f "$image_id"
    done
    echo "[1/3] [DONE] Successfully deleted latest sastre-pro image"
fi

files_delete=(
    "$HOME/sastre-pro/container_engine.sh"
    "$HOME/sastre-pro/sastre-pro.sh"
    "$HOME/sastre-pro/uninstall.sh"
    "$HOME/sastre-pro/uninstall.app"
)

for file in "${files_delete[@]}"; do
    if [ -e "$file" ]; then
        rm -rf "$file"
        if [ $? -eq 0 ]; then
            echo "[DONE] Successfully deleted $file"
        else
            echo "[ERROR] Could not delete $file" >&2
        fi
    else
        echo "[INFO] $file does not exist, skipping deletion"
    fi
done

echo "=============Sastre-Pro application uninstall process finished============="
CONTAINER_NAME=$(basename "$CONTAINER_EXE")
dialog_message="The Sastre-Pro image has been successfully unloaded from the $CONTAINER_NAME container engine."
osascript -e "display dialog \"$dialog_message\" with title \"Sastre-Pro\" buttons {\"OK\"} default button \"OK\" with icon POSIX file \"$HOME/sastre-pro/sastre.icns\""
[ -e ~/sastre-pro/sastre.icns ] && rm -rf ~/sastre-pro/sastre.icns
if [ $? -eq 0 ]
then
  echo "[DONE] Successfully deleted sastre-pro icon"
else
  echo "[ERROR] Could not delete sastre-pro icon" >&2
fi
echo "NOTE: Please delete ~/sastre-pro/sastre-volume folder manually (if you choose so)"
exit 0