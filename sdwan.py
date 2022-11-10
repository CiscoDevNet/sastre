#! /usr/bin/env python3
"""
Sastre - Cisco-SDWAN Automation Toolset

"""
import re
import sys

from cisco_sdwan.__main__ import main

if __name__ == '__main__':
    sys.argv[0] = re.sub(r'(-script\.pyw?|\.exe)?$', '', sys.argv[0])
    sys.exit(main())
