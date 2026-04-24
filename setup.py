from setuptools import setup, find_packages

setup(
    name='modstan',
    version='2.0.1',
    description='Modbus TCP Data Logger — multi-device, storage-agnostic, production-ready',
    author='F4NTech',
    python_requires='>=3.10',
    packages=find_packages(),
    install_requires=[
        'pyModbusTCP>=0.3.0',
    ],
    extras_require={
        'postgres': ['psycopg2-binary>=2.9.0'],
        'mariadb' : ['mysql-connector-python>=8.0.0'],
        'all'     : [
            'psycopg2-binary>=2.9.0',
            'mysql-connector-python>=8.0.0',
        ],
    },
    entry_points={
        'console_scripts': [
            'modstan=cli.commands:main',
        ],
    },
)
