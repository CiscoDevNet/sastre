"""
    Template Migration - Tool to migrate vEdge-cEdge combined vManage templates to cEdge only vManage templates (20.1 onwards).
"""

__copyright__    = "Copyright (c) 2019-2020 Cisco Systems, Inc. and/or its affiliates"
__version__      = "0.18 [08 April 2020]"
__author__       = "Shreyas Ramesh, Shayan Ahmed"
__email__        = "shrerame@cisco.com, shayahme@cisco.com"

# ----------------- #
#  Generic Imports  #
# ----------------- #

import os
import sys
import json
import copy
import numbers
import argparse
from collections import deque, OrderedDict
from datetime import datetime
import logging

# -------------------- #
#  Miscellaneous Code  #
# -------------------- #

currentChangeLogDirPath = os.path.join(os.getcwd(), "logs")
if not os.path.exists(currentChangeLogDirPath):
    os.makedirs(currentChangeLogDirPath)

def setup_logger(name, logFile, level=logging.DEBUG):
    """To setup as many loggers as you want"""

    handler = logging.FileHandler(logFile)
    handler.setFormatter(LOG_FORMATTER)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)

    return logger

# ------------------- #
#  Global Parameters  #
# ------------------- #

LOG_FORMATTER = logging.Formatter("[%(asctime)s %(name)-12s] %(levelname)-8s %(message)s", "%m-%d %H:%M")
MIGRATION_CHANGE_LOG_PATH = os.path.join(currentChangeLogDirPath, "migration_operations.log")


class TemplateUtils:
    def __init__(self):
        self.currentDirPath = os.path.dirname(__file__)
        self.obejectPairsHook = OrderedDict

    def readJsonFromFile(self, directory, JSONFilename):
        with open(os.path.join(directory, JSONFilename)) as JSONFile:
            return json.load(JSONFile, object_pairs_hook=self.obejectPairsHook)

    def readJsonFromPath(self, path):
        with open(path) as JSONFile:
            return json.load(JSONFile, object_pairs_hook=self.obejectPairsHook)


    def writeJsonToFile(self, directory, JSONFilename, data):
        if not os.path.exists(directory):
            os.makedirs(directory)
        with open(os.path.join(directory, JSONFilename), "w+") as JSONFile:
             json.dump(data, JSONFile, indent=4)

    def generateFinalLevelDefinitionsIfExist(self, fieldHierarchyList,
                                             templateDefinition):
        """
        Generates all leaf level json objects having the data path matching
        `fieldHierarchyList`.
        If leaf level object does not exist, returns without an object.

        Args:
            fieldHierarchyList: List; List of keys that together represent
            field hierarchy.
            templateDefinition: JSON; Represented with `obejectPairsHook`

        Returns:
            Leaf level field JSON value OR None
        """
        currentFieldValue = templateDefinition
        while len(fieldHierarchyList) > 0:
            # Select the first level key's JSON value
            nextLevelKey = fieldHierarchyList[0]
            nextLevelJSONValue = currentFieldValue.get(nextLevelKey, None)
            if nextLevelJSONValue is not None:
                # Field's value exists. Continue to next level
                fieldHierarchyList.popleft()
                currentFieldValue = nextLevelJSONValue
            elif nextLevelJSONValue is None:
                # If vipObjectType is Tree then continue looking.
                if currentFieldValue.get("vipObjectType", "") == "tree":
                    JSONArray = currentFieldValue.get("vipValue", None)
                    for nextTemplateObject in JSONArray:
                        for _ in self.generateFinalLevelDefinitionsIfExist(copy.copy(fieldHierarchyList),
                                                                           nextTemplateObject):
                            yield _
                # Otherwise, stop and return None.
                return
        yield currentFieldValue


class v2cMigrator():
    def __init__(self, loadedTemplate, newTemplateType, operation, cls, fieldHierarchyList,
                 oldTemplateName, rangeMin=None, rangeMax=None, Default=None):
        self.templateUtil = TemplateUtils()
        self.template = loadedTemplate
        self.templateDefinition = self.template["templateDefinition"]
        self.template["templateType"] = newTemplateType
        self.operation = operation.strip()
        self.fieldHierarchyList = fieldHierarchyList
        self.fieldHierarchyListCopy = list(fieldHierarchyList)
        self.rangeMin = rangeMin
        self.rangeMax = rangeMax
        self.Default = Default
        self.validateOperationParameters()
        self.oldTemplateName = oldTemplateName
        self.cls = cls


    def run(self):
        if self.operation == "remove":
            isRemoved = []
            self.operRemove(self.fieldHierarchyList, self.templateDefinition, isRemoved)
            if True in isRemoved:
                self.cls.log_info("Field `{}` Removed from {}".format('/'.join(self.fieldHierarchyListCopy), self.oldTemplateName))
        elif self.operation == "range":
            self.operRange()
        elif self.operation == "default":
            self.operDefault()


    def validateOperationParameters(self):
        if self.rangeMin is None and self.rangeMax is None and self.Default is None:
            assert(self.operation == "remove")
        elif self.rangeMin is not None and self.rangeMax is not None and self.Default is None:
            assert(self.operation == "range")
        elif self.rangeMin is None and self.rangeMax is None and self.Default is not None:
            assert(self.operation == "default")


    def operRemove(self, fieldHierarchyList, templateDefinition, isRemoved):
        """
        Removes the JSONValue for the leaf key specified in fieldHierarchyList.

        For example, assume fieldHierarchyList is ['view', 'name'], then
        operRemove will first lookup the JSONValue of key 'view'. Next,
        it will look up JSONValue of key 'name' if it exists, and then deletes
        the JSONValue.
        """
        currentFieldValue = templateDefinition
        while len(fieldHierarchyList) > 1:
            nextLevelKey = fieldHierarchyList[0]
            nextLevelJSONValue = currentFieldValue.get(nextLevelKey, None)
            if nextLevelJSONValue is not None:
                currentFieldValue = nextLevelJSONValue
                fieldHierarchyList.popleft()
            elif nextLevelJSONValue is None and currentFieldValue.get('vipObjectType', '') == 'tree':
                JSONArray = currentFieldValue.get('vipValue', None)
                for nextTemplateObject in JSONArray:
                    self.operRemove(copy.copy(fieldHierarchyList), nextTemplateObject, isRemoved)
                return
            else:
                # Value and children for this key does not exist. Does not exist yet.
                return

        nextLevelKey = fieldHierarchyList[0]
        removedField = currentFieldValue.pop(nextLevelKey, None)
        if removedField is None and currentFieldValue.get('vipObjectType', '') == 'tree':
            JSONArray = currentFieldValue.get('vipValue', None)
            for nextTemplateObject in JSONArray:
                self.operRemove(copy.copy(fieldHierarchyList), nextTemplateObject, isRemoved)
        else:
            if removedField is None:
                return
            isRemoved.append(True)

        # Implicit Return at this point


    def operRange(self):
        """
        If vipValue is below the self.rangeMin or greater than self.rangeMax,
        update vipValue to the respective rangeMin or rangeMax.
        If key cannot be found in the template, check if it is a tree (by looking at vipValue).
        If tree, pass remaining fieldHierarchyList and call operRange for each child.
        Updates only for dataType number.
        """
        for JSONValue in self.templateUtil.generateFinalLevelDefinitionsIfExist(self.fieldHierarchyList,
                                                                                self.templateDefinition):
            vipValue = JSONValue.get("vipValue", None)
            if isinstance(vipValue, numbers.Number):
                if self.rangeMin:
                    if vipValue < self.rangeMin:
                        self.cls.log_info("Field `{}` Min Range Updated in {} - Updated vipValue from {} to {}".format('/'.join(self.fieldHierarchyListCopy), self.oldTemplateName, vipValue, self.rangeMin))
                        JSONValue["vipValue"] = self.rangeMin
                elif self.rangeMax:
                    if vipValue > self.rangeMax:
                        self.cls.log_info("Field `{}` Max Range Updated in {} - Updated vipValue from {} to {}".format('/'.join(self.fieldHierarchyListCopy), self.oldTemplateName, vipValue, self.rangeMax))
                        JSONValue["vipValue"] = self.rangeMax


    def operDefault(self):
        """
        Check if vipType is ignore and vipValue of the leaf field is the
        same as the Default value provided.
        If either is not True, then change vipType to Constant
        """
        for JSONValue in self.templateUtil.generateFinalLevelDefinitionsIfExist(self.fieldHierarchyList,
                                                                                self.templateDefinition):
            if JSONValue is not None:
                vipValue = JSONValue.get("vipValue", None)
                if JSONValue.get("vipType", "") == "ignore" and vipValue != self.Default:
                    self.cls.log_info("Field `{}` Default Updated in {} - Updated vipType to `Global/constant` and vipValue from {} to {}".format('/'.join(self.fieldHierarchyListCopy), self.oldTemplateName, vipValue, self.Default))
                    JSONValue["vipType"] = "constant"
                    JSONValue["vipValue"] = self.Default


class JSONInputDigest():
    def __init__(self, inputFileName):
        self.inputFileName = inputFileName
        self.JSONInput = TemplateUtils().readJsonFromPath(inputFileName)
        self.oldfilterDeviceTypeList = ["vedge-ISR1100-6G", "vedge-ISR1100-4G",
                                     "vedge-ISR1100-4GLTE", "vedge-cloud",
                                     "vedge-1000", "vedge-2000", "vedge-100",
                                     "vedge-100-B", "vedge-100-WM", "vedge-100-M",
                                     "vedge-5000", "vedge-nfvis-CSP2100",
                                     "vedge-nfvis-CSP-5444", "vedge-nfvis-CSP2100-X1",
                                     "vedge-nfvis-CSP2100-X2", "vedge-nfvis-UCSC-M5",
                                     "vedge-nfvis-UCSC-E"]
        self.filterDeviceTypeList = ["vedge-ISR1100-6G", "vedge-ISR1100-4G",
        "vedge-ISR1100-4GLTE", "vedge-cloud",
        "vedge-1000", "vedge-2000", "vedge-5000",
        "vedge-100", "vedge-100-B", "vedge-100-M",
        "vedge-100-WM", "vsmart", "vbond"]

    def isNotEmpty(self, value):
        if value:
            return True
        return False

    def requiredParametersCheck(self, currentMigration, requiredParameters, templateDefinitionFile, cls):
        if all(key in currentMigration.keys() for key in requiredParameters):
            if all(self.isNotEmpty(currentMigration[key]) for key in requiredParameters):
                return True
            else:
                for key in requiredParameters:
                    if not self.isNotEmpty(currentMigration[key]):
                        cls.log_error("RequirementError: {}  - Required feature template parameter `{}` is empty".format(templateDefinitionFile, key))
        else:
            for key in requiredParameters:
                if key not in currentMigration.keys():
                    cls.log_error("RequirementError: {} - Required feature template parameter `{}` is undefined".format(templateDefinitionFile, key))
        return False


    def migrate(self, fromvManageVersion, to_version, cls, src_dir, dest_dir, prefix):
        for td_idx, templateDefinitionFile in enumerate(os.listdir(src_dir)):
            try:
                vEdgeTemplateDefinition = TemplateUtils().readJsonFromPath(os.path.join(src_dir, templateDefinitionFile))
            except:
                cls.log_error("FileError: Could not read template definition file: {}".format(templateDefinitionFile))
                continue

            try:
                vEdgeTemplateType = vEdgeTemplateDefinition["templateType"]
            except:
                cls.log_error("KeyError: {} - Could not find key `templateType`".format(templateDefinitionFile))
                continue

            wasMigrated = False

            for currentMigration in self.JSONInput:
                if currentMigration["fromvManageVersion"] == fromvManageVersion and\
                    currentMigration["tovManageVersion"] == to_version:
                    wasMigrated = True

                    try:
                        templateTypeListDict = currentMigration["templateTypeList"]
                    except:
                        cls.log_error("KeyError: JSONInput - Could not find key `templateTypeList`")
                        continue

                    for currentFeature in templateTypeListDict:
                        if vEdgeTemplateType == currentFeature["fromFeatureName"]:
                            if not self.requiredParametersCheck(currentFeature, ["fromFeatureName", "toFeatureName"], templateDefinitionFile, cls):
                                continue
                            fromFeatureName = currentFeature["fromFeatureName"]
                            loadedTemplate = vEdgeTemplateDefinition

                            toFeatureName = currentFeature["toFeatureName"]
                            toDirectory = dest_dir

                            try:
                                oldTemplateName = loadedTemplate["templateName"]
                                loadedTemplate["templateName"] = prefix + oldTemplateName
                            except:
                                cls.log_error("KeyError: FeatureTemplate - Could not find key `templateName`")
                                continue

                            try:
                                deviceTypeList = set(loadedTemplate["deviceType"])
                                deviceTypeList.difference_update(set(self.filterDeviceTypeList))
                                loadedTemplate["deviceType"] = list(deviceTypeList)
                            except:
                                cls.log_error("KeyError: FeatureTemplate - Could not find key `deviceType`")
                                continue

                            if not currentFeature["listOfTasks"]:
                                loadedTemplate["templateType"] = toFeatureName

                            for oper in currentFeature["listOfTasks"]:
                                if not self.requiredParametersCheck(oper, ["operation", "fieldHierarchyList"], templateDefinitionFile, cls):
                                    continue
                                operation = oper["operation"]
                                fieldHierarchyList = oper["fieldHierarchyList"]

                                rangeMin = oper.get("rangeMin", None)
                                rangeMax = oper.get("rangeMax", None)
                                default = oper.get("default", None)

                                try:
                                    migrateInstance = v2cMigrator(loadedTemplate, toFeatureName, operation, cls, deque(fieldHierarchyList), oldTemplateName, rangeMin, rangeMax, default).run()
                                except:
                                    cls.log_error("MigrationError: Could not perform {} for fieldHierarchyPath [{}] on file {}".format(operation, ','.join(fieldHierarchyList), templateDefinitionFile))
                                    continue

                            # Write to current directory
                            try:
                                TemplateUtils().writeJsonToFile(toDirectory, loadedTemplate["templateId"] + ".json", loadedTemplate)
                            except:
                                cls.log_error("FileError: Could not write migrated template to file {}".format(prefix + templateDefinitionFile))

            if not wasMigrated:
                raise Exception("Migration from " + fromvManageVersion + " to " + to_version + " is not defined.")


class ArgClass:
    """ So that we don't have to duplicate argument info when
        the same parameter is used in more than one mode.
    """

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', action='version',
                        version='%(prog)s {version}'.format(version=__version__))

    defaultDestDir = os.path.join(os.path.dirname(__file__), "migratedTemplates")

    dest_dir = ArgClass("-d", "--dest-dir", help="Directory to put cEdge template definitions into", default=defaultDestDir)

    prefix = ArgClass("-p", "--prefix", help="Prefix for all cEdge template definitions", default="cisco_")

    subparsers = parser.add_subparsers(help="sub-commands", dest="mode")

    parser_migrate = subparsers.add_parser("migrate", help="Migrate Template Definitions")
    parser_migrate.add_argument("from_version", help="From vManage version")
    parser_migrate.add_argument("to_version", help="To vManage version")
    parser_migrate.add_argument("src_dir", help="Directory holding all vEdge template definitions")
    parser_migrate.add_argument("json_input", help="Path to JSON file holding all version specific migration tasks")
    parser_migrate.add_argument("logger", help="Path to file holding logs")
    parser_migrate.add_argument(*dest_dir.args, **dest_dir.kwargs)
    parser_migrate.add_argument(*prefix.args, **prefix.kwargs)

    args = parser.parse_args(argv)
    sys.stdout.flush()

    mode = args.mode
    now = datetime.utcnow()

    # Read Version and Release Date here

    if mode == "migrate":
        from_version = args.from_version
        to_version = args.to_version
        src_dir = args.src_dir
        json_input = args.json_input
        loggerPath = args.logger

if __name__ == "__main__":
    main(sys.argv[1:])
