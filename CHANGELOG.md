Sastre 1.3 [July 23, 2020]
============================

####Enhancements:
- Split into Sastre and Sastre-Pro. Sastre-Pro will contain additional features. Current plan is to maintain release numbers in sync between the two variants.

Sastre 1.2 [June 22, 2020]
============================

####New features:
- Migrate task, allowing migration of feature templates and device templates to be compatible with vManage 20.1.
- Transform option added to list task, allowing user to test name-regex transforms against existing item names.
- References option added to show-template task, providing information on which device-templates reference a particular
  feature template.

####Enhancements:
- vManage information (address, user and password) is no longer required when a task uses local workdir as
  source. For instance, list or show-template tasks when --workdir is provided.
- Backup task now allows disabling of the automatic workdir rollover mechanism using the --no-rollover option. This
  is useful when the backup directory is being managed by an external version control tool (e.g. git).
- Backup task now also include device configurations when tag 'all' is used. This includes WAN edges and controllers,
  also RFS and CFS configurations.


Sastre 0.37 [April 21, 2020]
============================

####Fixes:
- Restore task with --attach option when one or more WAN Edges or vSmarts are offline would show a warning that the
  template attach failed, even though it was successfully attached (with sync pending for offline devices).
  Similarly, if one or more vSmarts are offline vSmart policy would not be activated (with sync pending).
  This has been fixed.


Sastre 0.36 [April 10, 2020]
============================

####Enhancements:
- Validated support for vManage 20.1 and included new API endpoints:
    - Policy lists: media profile, translation profile, translation rules, supervisory disconnect, FQDN
    - Policy definitions: Dial peer, SRST phone profile, FXS port, FXO port, FXS-DID port, SSL decryption, SSL UTD profile
    - Voice policies, custom application policies
- New API model versioning scheme to restrict REST API queries to only the endpoints supported by the target vManage.
- User is now prompted for vManage address, username or password if they are not provided via command line or environment variables.


Sastre 0.35 [Mar 3, 2020]
==========================

####Enhancements:
- Backup task now also backup device certificates when the 'all' tag is used. The restore task does not restore
  certificates.
- New certificate task, allowing device certificate validity status to be restored from a backup or set to a
  desired value (i.e. valid, invalid or staging).
- List task now contains two sub-modes: configuration or certificate. List configuration works the same way as on
  previous releases by listing configuration items (e.g. device templates, feature templates, policies, etc.).
  The new certificate sub-mode allows listing of device certificate information from vManage or from a backup.
- Restore task now verifies whether vBond is configured (Administration > Settings > vBond). If vBond is not
  configured, device templates are skipped from the restore as it would otherwise fail. A warning message notifies
  when this happens.


Sastre 0.34 [Jan 9, 2020]
==========================

####Enhancements:
- Validated support for vManage 19.3 and included new API endpoints supporting device access policies.
- Included vManage version check. A warning is displayed during restore task if the vManage version on backup is
  newer than the version on target vManage. Maintenance releases (i.e. 3rd digit in the version number) are ignored
  for the purpose of this verification.


Sastre 0.33 [Dec 6, 2019]
==========================

####Enhancements:
- Sastre is now published to PyPI as cisco-sdwan package. When installed via pip, sdwan or sastre can be used to
  run the application.
- When installed via source on github, the application can now be called using sdwan.py or sastre.py.


Sastre 0.31 [Nov 18, 2019]
==========================

####Enhancements:
- Template attach and reattach functions now support CLI templates. This means that restore --attach and --force
  options now support CLI templates in addition to feature-based device templates.
- Added --regex option to backup task, allowing finner granularity into items included in the backup.


Sastre 0.30 [Oct 25, 2019]
==========================

####Enhancements:
- Backups now always create a new workdir. If the target workdir is already present, Sastre will save it with a
  number extension. For instance, if the target workdir is 'backup_production_20191022' and there is already a
  backup under this directory, this existing backup is moved to 'backup_production_20191022_1'. The number extension
  can go up to 99. At this point Sastre starts deleting the previous backup.

####Non-backwards compatible enhancements:
- Backup database is changed in release 0.30. Individual items (e.g. device templates, feature templates, etc) are
  now stored with a filename containing the actual item name, as opposed to the item uuid. The directories where
  items are saved were also changed.
  In order to guarantee a filesystem safe filename, item name characters other than a-z, A-Z, ' ', '-' or '_' are
  replaced with an underscore '_' in the filename. In case of name collision, Sastre falls back to using filenames
  in the format <item name>_<item id>. For instance, if there is one device template named VEDGE_1K_v1 and another
  VEDGE/1K/v1, both will have the same filename-safe name (i.e. VEDGE_1K_v1). Sastre will save them as
  VEDGE_1K_v1_<uuid item 1>.json and VEDGE_1K_v1_<uuid item 2>.json.
  The latest release using the old backup format was tagged as 'v0.2'. If there is a need to use older backups,
  just git checkout this tag (git checkout v0.2).


Sastre 0.22 [Oct 10, 2019]
==========================

Enhancements:
- Improved error handling for malformed json files in the backup. When backup json files fail to be loaded
  (i.e. parsed) additional details are now provided in the log message.


Sastre 0.21 [Oct 5, 2019]
==========================

####Enhancements:
- Added --force option to restore task. vManage items with the same name as backup items but with differences in
  their contents are updated with data from the backup. README file contains additional details.


