from setuptools import find_packages, setup


def _fetch_requirements(path: str) -> list[str]:
    with open(path, encoding='utf-8') as fd:
        return [r.strip() for r in fd.readlines() if r.strip() and not r.startswith('#')]


setup(
    name='trainstack',
    version='0.1.0',
    author='trainstack Team',
    packages=find_packages(include=['trainstack_plugins*']),
    include_package_data=True,
    install_requires=_fetch_requirements('requirements.txt'),
    python_requires='>=3.10',
)
