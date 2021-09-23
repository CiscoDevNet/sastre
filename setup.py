import setuptools
from cisco_sdwan import __version__, __author__, __email__, __url__

with open("README.md", "r") as f:
    long_description = f.read()

setuptools.setup(
    name="cisco-sdwan",
    version=__version__,
    author=__author__,
    author_email=__email__,
    description="Automation Tools for Cisco SD-WAN Powered by Viptela",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url=__url__,
    packages=setuptools.find_packages(),
    package_data={
        "cisco_sdwan.migration": ["*.json", "feature_templates/*.json"]
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.8',
    install_requires=[
        'requests',
        'PyYAML',
        'pydantic'
    ],
    entry_points={
        'console_scripts': [
            'sdwan=cisco_sdwan.cmd:main',
            'sastre=cisco_sdwan.cmd:main',
        ],
    },
)
