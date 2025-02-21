# Sastre-Pro - Windows installer builder steps

NOTE: Installer supports both Podman and Docker. So, use either Podman or Docker to build sastre-pro image.</br>

1. Go to root directory of Sastre-Pro and run below command to generate Application image
```
docker build --no-cache -t localhost/sastre-pro:latest .
```
2. Verify docker image is created
```
docker images
```
3. Save Sastre-Pro docker image as tar file
```
docker save -o sastre-pro.tar localhost/sastre-pro:latest
```

## Login to Windows machine (X64 and ARM64 architecture)  and copy "windows" folder and files to ${LOCATION} and follow below steps

### Pre-requisite
Download [NSIS](https://nsis.sourceforge.io/Download) in Windows machine for compiling and generating installer for windows


4. Modify Windows installer files if needed

Name | Description
--- | ---
[Release Notes](sastre-pro.nsi)|Update WelcomePage function
[License](LICENSE.txt)|Update license
[Run Sastre Steps](sastre-pro.nsi)|Update RunSastrePage function
[Uninstall Sastre Steps](sastre-pro.nsi)|Update UninstallSastrePage function
[Application Logo](sastre-pro.ico)|Update Application logo
[Main script](main.bat)|Update main script
[Install script](install.bat)|Update install script
[Uninstall script](uninstall.bat)|Update uninstall script


5. Go to "${LOCATION}\windows" folder and run below command (replace {VERSION} placeholder with actual value)
```
main.bat Sastre-Pro {VERSION}
```

- NOTE: Above command will create target folder with required files 

6. copy the sastre-pro.tar file generated in step 3 to "${LOCATION}\windows\target\" in Windows machine

7. Open NSIS tool and select "sastre-pro.nsi" file located at "${LOCATION}\windows\target\" for compiling and generating Sastre-Pro installer

8. After the successful compilation by NSIS tool, the Windows installer .exe fle is created for Sastre-Pro application at the following location : "${LOCATION}\windows\target\sastre-pro.exe"

9. Run sastre-pro.exe to verify installation, running and uninstallation of Sastre-Pro using both Podman and Docker container engines

10. Follow Cisco SWIMS process to sign the Sastre-Pro installer (i.e. sastre-pro.exe) for both Windows X64 and Windows ARM64