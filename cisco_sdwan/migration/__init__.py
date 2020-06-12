from pathlib import Path
from cisco_sdwan.base.models_vmanage import FeatureTemplate
from cisco_sdwan.base.processor import ProcessorException

current_dir = Path(__file__).resolve().parent


def module_dir():
    return current_dir


# Load built-in factory default cedge_global and cedge_aaa
factory_cedge_global = FeatureTemplate.load(module_dir(), False, use_root_dir=False,
                                            item_name='Factory_Default_Global_CISCO_Template',
                                            item_id='300d7759-cc0a-4cd7-90c0-eb52adc27f2f')
if factory_cedge_global is None:
    raise ProcessorException('Unable to find factory default cEdge global template')

factory_cedge_aaa = FeatureTemplate.load(module_dir(), False, use_root_dir=False,
                                         item_name='Factory_Default_AAA_CISCO_Template',
                                         item_id='add276c5-45b0-4493-a559-5a07b15cbdeb')
if factory_cedge_aaa is None:
    raise ProcessorException('Unable to find factory default Cisco AAA template')
