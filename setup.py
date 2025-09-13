from setuptools import setup

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="smartmove",
    version="0.1.0",
    author="Leonardo Puccio",
    author_email="me@leonardopuccio.dev",
    description="Cross-filesystem file mover with hardlink preservation",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/LeonardoPuccio/smartmove",
    py_modules=["smartmove", "file_mover", "cross_filesystem", "directory_manager"],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: System Administrators",
        "Topic :: System :: Filesystems",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    python_requires=">=3.10",
    entry_points={
        "console_scripts": [
            "smv=smartmove:main",
        ],
    },
)
