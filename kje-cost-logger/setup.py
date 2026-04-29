"""kje-cost-logger — empire-wide cost reporting client.

Every KJE product that calls Anthropic, OpenAI, or any LLM API uses this
module to push cost rows into BridgeDeck's /cost/ingest endpoint. See
docs/EMPIRE_COST_LOGGING_BUILD_CARD.md for the full doctrine.
"""
from setuptools import setup, find_packages

setup(
    name="kje-cost-logger",
    version="1.0.0",
    description="Empire-wide cost reporting client for KJE products",
    long_description=__doc__,
    long_description_content_type="text/plain",
    author="DevelopingRiches Inc / Jim Harris",
    python_requires=">=3.9",
    packages=find_packages(),
    install_requires=[
        "httpx>=0.25",
        "pydantic>=2",
    ],
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
