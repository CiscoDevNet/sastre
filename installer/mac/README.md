# Sastre-Pro - macOS installer builder steps

Some notes: 
- Installer supports both Podman and Docker. So, use either Podman or Docker to build sastre-pro image.
- Follow below steps in both Mac Apple chip and Intel chip <br>

1. Go to root directory of Sastre-Pro and run below command to generate Application image
```
docker build --no-cache -t localhost/sastre-pro:latest .
```
2. Verify sastre-pro docker image is created
```
docker images
```
3. Save sastre-pro docker image as tar file
```
docker save -o sastre-pro.tar localhost/sastre-pro:latest
```
4. Compress the tar file
```
gzip sastre-pro.tar 
```
5. copy the sastre-pro.tar.gz file generated in previous step to {SASTRE-PRO_HOME}/installer/mac/application/

6. Modify macOS installer files

Name | Description
--- | ---
[Release Notes](darwin/Resources/welcome.html)|Update release notes
[License](darwin/Resources/LICENSE.txt)|Update license
[Summary](darwin/Resources/conclusion.html)|Update summary details
[Application Logo](darwin/Resources/banner.png)|Update Application logo
[Caution icon](darwin/Resources/caution.png)|Update Caution icon
[Sastre-Pro icon](darwin/Resources/sastre.icns)|Update Sastre-Pro icon
[Post install script](darwin/scripts/postinstall)|Update Post install script
[Uninstall script](darwin/Resources/uninstall.sh)|Update uninstall script
[Uninstall app](darwin/Resources/uninstall.app)|Update uninstall sastre-pro application (Follow "Steps to update Sastre-Pro uninstall Application" section below)

7. Go to {SASTRE-PRO_HOME}/installer/mac and run below command to generate Sastre-Pro installer (replace VERSION placeholder with actual value) 
```
./build-macos-x64.sh Sastre-Pro {VERSION}
```
NOTE: Above command prompts for "Do you wish to sign the installer (You should have Apple Developer Certificate) [y/N]?", Enter N

After the successful execution of above command, the macOS installer builder will create .pkg file of Sastre-Pro application on the following location:

#### Un-signed Package:
```
target/pkg/
```

8. Run sastre-pro.pkg to verify installation, running and uninstallation of Sastre-Pro using both Podman and Docker container engines

9. Follow Cisco SWIMS process to sign the Sastre-Pro installer (i.e sastre-pro.pkg) for both Mac Apple chip and Mac Intel chip



## Verify signed .pkg files

To verify the signed .pkg file run the following command:
```
pkgutil --check-signature <SIGNED_INSTALLER_NAME>.pkg
```
You will see an output with SHA1 fingerprint after the above command if the .pkg file’s sign validation is successful.


# Steps to update Sastre-Pro uninstall application

1. Open and update [sastre-pro](uninstall.applescript) applescript source
2. Save the [sastre-pro](uninstall.applescript) applescript as application to "darwin/Resources/" as "uninstall.app" application file
    1. In the Finder app, goto "{SASTRE-PRO_ROOT}/installer/mac/uninstall.applescript" 
    2. Right-click on the "uninstall.applescript" file
    3. select "Open With -> Script Editor" from the context menu
    4. Save the script as an application (i.e uninstall.app) : 
        - Choose from Menu "File" > "Export" 
        - Select destination as "darwin/Resources/"
        - Select File Format as "Application" from drop-down
        - Click save
3. Assign Sastre-Pro application icon to uninstall.app
    1. In the Finder app, goto "{SASTRE-PRO_ROOT}/installer/mac/darwin/Resources/"
    2. Right-click on the "uninstall.app" application file created in above step
    3. select "Get Info" from the context menu 
    4. Drag the "{SASTRE-PRO_ROOT}/installer/mac/darwin/Resources/sastre.icns" icon file(Follow "Steps to create/update sastre.icns icon file" section below) onto the icon in the top-left corner of the Info window. You should see the icon change to the one you dragged.
    5. Close the info window
    6. Now "uninstall.app" should have Sastre-Pro icon
    

# Steps to create/update sastre.icns icon file

1. Create a sastre image file of type png/jpeg format
2. Convert png/jpeg file to ICNS format
3. Steps to create a sastre ICNS format
    1. Create "sastre.iconset" folder
    2. Place png/jpeg files of different sizes inside "sastre.iconset" folder (created in above step): 16x16, 32x32, 64x64, 128x128, 256x256, 512x512, and optionally 1024x1024 pixels. Each file should follow the naming convention "icon_16x16.png", "icon_32x32.png", and so on
    3. From Terminal , go to directory where "sastre.iconset" folder is present.
    4. Run below command to generate "sastre.icns" icon file
        1. iconutil -c icns sastre.iconset 
    5. "sastre.icns" file is generated at same level as "sastre.iconset" folder
    6. copy "sastre.icns" file to "{SASTRE-PRO_ROOT}/installer/mac/darwin/Resources/sastre.icns"
 