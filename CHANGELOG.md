Sastre 1.15 [September 25, 2021]
================================

#### Enhancements:
- [#83] Initial support for the vManage 20.5.x, included the following API endpoints:
  - Policy lists: Expanded community, Geo location
- [#94] Support for multi-tenant vManage deployment.
- [#45] All tasks that provide table output (e.g. show, list, etc) have been enhanced to allow exporting those tables as 
  JSON encoded files. This is done via --json option added to each task.
- Show task was expanded with new realtime commands:
  - orchestrator connections, orchestrator local-properties, orchestrator valid-vedges, orchestrator valid-vsmarts
  - arp vedge, arp cedge
  - hardware inventory
- Report task has been significantly expanded:
  - Diff option added to report task, allowing comparison between reports. Diff can be exported as html or text.
  - Option to customize which tasks/commands to include in the report. Via YAML file or JSON-formatted string.
  - Default report now also include show state and show devices tasks.


#### Behavior changes:
- Backup task on prior versions would include saving the running configuration from all nodes whenever tag 'all' was
  used (i.e. backup all ...). Since this can be time-consuming in a large network and is not needed by the restore task,
  it is now made an optional flag for the backup task: --save-running. By default, a 'backup all' will not include 
  saving the running configs.

Sastre 1.14 [July 13, 2021]
============================

#### Enhancements:
- [#55] Support for vManage 20.4.x and included new API endpoints:
    - Policy lists: Protocol, Port, App-Probe
    - Policy definitions: Rule Set
- [#22] Most tasks with a --regex option now also include a --not-regex option. While --regex is used to select items to 
  include (i.e. perform task operation), --not-regex is used to define items not to include. That is, include all items, 
  except the ones matching --not-regex.
- [#79] "show-template values" now have --regex and --not-regex matching on template name or ID, which is similar to the
  behavior of the "list config" task. The individual --name and --id options became redundant and were removed.
  
#### Fixes:
- [#84] Version validator used by migrate task was violating Dlint DUO138. This has been fixed.

Sastre 1.13 [April 30, 2021]
============================

#### Enhancements:
- [#67] Performance improvements to show realtime commands. Thread pool is now used to send multiple requests in parallel. 
  Pool size is fixed at 10.
- [#68] Added show realtime omp adv-routes command, displaying advertised OMP routes from one or more WAN edges / vSmarts.
- [#71] Validation of template attach/detach, in a testbed with 200 devices. Action timeout increased to 20 minutes.
- [#72] Show-template values now by default display values for all templates with attachments when no match criteria is
  provided (i.e. no --name, --id or --regex).
- [#70] All show command output can now be exported as CSV files.
- [#60] Show task has been expanded with state and statistics subcommands.

Sastre 1.12 [March 10, 2021]
============================

#### Enhancements:
- [#59] Template attach requests used in restore task (--attach and --force options) are improved to split attachment 
  requests in chunks of up to 10 devices. Dry-run mode is now supported with --attach option.
- [#63] Template detach requests used in delete task (--detach option) are improved to split detach requests in chunks of
  up to 10 devices. Dry-run mode is now supported with --detach option.
- [#64] (Sastre-Pro) New attach task providing further customization on device template attach operations. Templates and 
  devices can be filtered by regular expressions and device properties (reachability, system-ip, etc). Also, the maximum 
  number of devices per vManage template attach request can be customized. By default, Sastre will split attach 
  requests in chunks of up to 10 devices.
- [#65] (Sastre-Pro) New detach task providing further customization on device template detach operations. Templates and 
  devices can be filtered by regular expressions and device properties (reachability, system-ip, etc). Also, the maximum 
  number of devices per vManage template detach request can be customized. By default, Sastre will split detach 
  requests in chunks of up to 10 devices.
  
In this version we are also bumping up the minimal Python requirements to 3.8.

Sastre 1.11 [November 25, 2020]
============================

#### Enhancements:
- [#20] Validated support for vManage 20.3.x and included new API endpoints:
    - Policy lists: fax protocol, modem passthrough, trunk group
    - Policy definitions: PRI ISDN port
- [#47] The data store location can now be customized via the SASTRE_ROOT_DIR environment variable. When SASTRE_ROOT_DIR is not set, the data store is data/ under the directory where Sastre is run. This is the default behavior, as in all previous releases. When SASTRE_ROOT_DIR is set, the data store becomes $SASTRE_ROOT_DIR/data/.
- [#48] Updated Dockerfile and container run instructions for better integration with CX CAT tool

#### Fixes:
- [#40] User not prompted for cx pid when it was not provided via cli or environment variable, if the task didn't require api. This has been fixed.

Sastre 1.10 [November 2, 2020]
============================

#### Enhancements:
- [#29] Support for VMANAGE_PORT environment variable as an option to set TCP port for target vManage.
- [#25] Python 3.9 support verified.

#### Fixes:
- [#10] A traceback would be generated on API authorization issues. E.g. read-only account used for a backup task (which requires POST calls). This has been fixed and a clear error message is now displayed.
- [#35] vBond configuration check on restore task not working on multi-tenant mode. This has been fixed.
- [#36] Migrate task would fail migration of cli-based device templates and feature templates containing a mix of vmanage and cEdge devices. This has been fixed.

Sastre 1.9 [October 13, 2020]
============================

#### Fixes:
- [#27] CustomApp Policy restore failure in 20.3.1. 

Sastre 1.8 [October 2, 2020]
============================

#### Enhancements:
- Added Dockerfile and instructions to build and run the container (in the readme file).

Sastre 1.7 [September 16, 2020]
============================

#### Enhancements:
- (Sastre-Pro) Including per-task time savings to AIDE metric collection. Also added support for CX project ID parameter.
- (Sastre-Pro) Added show dpi summary realtime command

Sastre 1.6 [September 2, 2020]
============================

#### Enhancements:
- Show software added to show task (Sastre-Pro feature).

#### Fixes:
- Improved show task to gracefully handle cases where older vManage/device releases may not have all queried table fields available. Whenever a particular device doesn't have a table field, "N/A" is returned.
- Report task would fail with no report generated if any of its subtasks fail. This has been fixed, a report is still created containing the output of all non-failed subtasks. 

Sastre 1.5 [September 2, 2020]
============================

#### New features:
- New Show task available only on Sastre-Pro. Enable execution of select real-time commands across multiple devices and easy visualization in tables.

Sastre 1.4 [August 12, 2020]
============================

#### New features:
- New Report task, which creates a report file consolidating the output of list configuration, list certificate, show-template values and show-template references.

#### Fixes:
- CustomApp policies were causing an exception during backup. This has been fixed.

Sastre 1.3 [July 23, 2020]
============================

#### Enhancements:
- Split into Sastre and Sastre-Pro. Sastre-Pro will contain additional features. Current plan is to maintain release numbers in sync between the two variants.

Sastre 1.2 [June 22, 2020]
============================

#### New features:
- Migrate task, allowing migration of feature templates and device templates to be compatible with vManage 20.1.
- Transform option added to list task, allowing user to test name-regex transforms against existing item names.
- References option added to show-template task, providing information on which device-templates reference a particular
  feature template.

#### Enhancements:
- vManage information (address, user and password) is no longer required when a task uses local workdir as
  source. For instance, list or show-template tasks when --workdir is provided.
- Backup task now allows disabling of the automatic workdir rollover mechanism using the --no-rollover option. This
  is useful when the backup directory is being managed by an external version control tool (e.g. git).
- Backup task now also include device configurations when tag 'all' is used. This includes WAN edges and controllers,
  also RFS and CFS configurations.


Sastre 0.37 [April 21, 2020]
============================

#### Fixes:
- Restore task with --attach option when one or more WAN Edges or vSmarts are offline would show a warning that the
  template attach failed, even though it was successfully attached (with sync pending for offline devices).
  Similarly, if one or more vSmarts are offline vSmart policy would not be activated (with sync pending).
  This has been fixed.


Sastre 0.36 [April 10, 2020]
============================

#### Enhancements:
- Validated support for vManage 20.1 and included new API endpoints:
    - Policy lists: media profile, translation profile, translation rules, supervisory disconnect, FQDN
    - Policy definitions: Dial peer, SRST phone profile, FXS port, FXO port, FXS-DID port, SSL decryption, SSL UTD profile
    - Voice policies, custom application policies
- New API model versioning scheme to restrict REST API queries to only the endpoints supported by the target vManage.
- User is now prompted for vManage address, username or password if they are not provided via command line or environment variables.


Sastre 0.35 [Mar 3, 2020]
==========================

#### Enhancements:
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

#### Enhancements:
- Validated support for vManage 19.3 and included new API endpoints supporting device access policies.
- Included vManage version check. A warning is displayed during restore task if the vManage version on backup is
  newer than the version on target vManage. Maintenance releases (i.e. 3rd digit in the version number) are ignored
  for the purpose of this verification.


Sastre 0.33 [Dec 6, 2019]
==========================

#### Enhancements:
- Sastre is now published to PyPI as cisco-sdwan package. When installed via pip, sdwan or sastre can be used to
  run the application.
- When installed via source on github, the application can now be called using sdwan.py or sastre.py.


Sastre 0.31 [Nov 18, 2019]
==========================

#### Enhancements:
- Template attach and reattach functions now support CLI templates. This means that restore --attach and --force
  options now support CLI templates in addition to feature-based device templates.
- Added --regex option to backup task, allowing finner granularity into items included in the backup.


Sastre 0.30 [Oct 25, 2019]
==========================

#### Enhancements:
- Backups now always create a new workdir. If the target workdir is already present, Sastre will save it with a
  number extension. For instance, if the target workdir is 'backup_production_20191022' and there is already a
  backup under this directory, this existing backup is moved to 'backup_production_20191022_1'. The number extension
  can go up to 99. At this point Sastre starts deleting the previous backup.

#### Non-backwards compatible enhancements:
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

#### Enhancements:
- Improved error handling for malformed json files in the backup. When backup json files fail to be loaded
  (i.e. parsed) additional details are now provided in the log message.


Sastre 0.21 [Oct 5, 2019]
==========================

#### Enhancements:
- Added --force option to restore task. vManage items with the same name as backup items but with differences in
  their contents are updated with data from the backup. README file contains additional details.


