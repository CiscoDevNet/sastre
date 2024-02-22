# Sastre-Pro - macOS installer builder steps

1. Go to root directory of Sastre-Pro and run below command to generate Application image
```
docker build --no-cache -t sastre-pro:latest .
```
2. Verify sastre-pro docker image is created
```
docker images
```
3. Save sastre-pro docker image as tar file
```
docker save -o sastre-pro.tar sastre-pro:latest
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
[Post install script](darwin/scripts/postinstall)|Update Post install script
[Uninstall script](darwin/Resources/uninstall.sh)|Update uninstall script

7. Go to {SASTRE-PRO_HOME}/installer/mac and run below command to generate Sastre-Pro installer (replace VERSION placeholder with actual value) 
```
./build-macos-x64.sh Sastre-Pro {VERSION}
```

After the successful execution of above command, the macOS installer builder will create .pkg file of Sastre-Pro application on the following location:

#### Signed Package:
```
target/pkg-signed/
```

#### Un-signed Package:
```
target/pkg/
```
That’s it. Now you can start the installation process by clicking the .pkg file.



## Signing .pkg files

Run the below command to sign the .pkg file
```
productsign --sign "Developer ID Installer: <CERTIFICATE_NAME_AND_ID>" <INSTALLER_NAME>.pkg
```
To verify the signed .pkg file run the following command:
```
pkgutil --check-signature <SIGNED_INSTALLER_NAME>.pkg
```
You will see an output with SHA1 fingerprint after the above command if the .pkg file’s sign validation is successful.
