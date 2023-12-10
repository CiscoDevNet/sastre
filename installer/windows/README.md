# Sastre-Pro - windows installer builder steps

1. Go to root directory of Sastre-Pro and run below command to generate Application image
```
docker build --no-cache -t sastre-pro:latest .
```
2. Verify docker image is created
```
docker images
```
3. Save Sastre-Pro docker image as tar file
```
docker save -o sastre-pro.tar sastre-pro:latest
```

## Login to Windows machine and copy "windows" folder and files to ${LOCATION}

### Pre-requisite
Download [NSIS](https://nsis.sourceforge.io/Download) for compiling and generating insaller for windows


4. Modify windows installer files if needed

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

6. copy the sastre-pro.tar file generated in step 3 to "${LOCATION}\windows\target\" in windows machine

7. Open NSIS tool and select "sastre-pro.nsi" file located at "${LOCATION}\windows\target\" for compiling and generating Sastre-Pro installer


#### After the successful compilation by NSIS tool, the windows installer .exe fle is created for Sastre-Pro application at the following location : "${LOCATION}\windows\target\sastre-pro.exe"