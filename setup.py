from pathlib import Path

from setuptools import setup, find_packages

version = '0.7.1'

here = Path(__file__).parent
long_description = (
    here.joinpath('README.rst').read_text(encoding='utf-8')
    + '\n\n'
    + here.joinpath('CHANGES.rst').read_text(encoding='utf-8')
)

setup(name='Products.FirebirdDA',
      version=version,
      description="Firebird database adapter for Zope 5",
      long_description=long_description,
      long_description_content_type='text/x-rst',
      # Get more strings from
      # http://pypi.python.org/pypi?:action=list_classifiers
      classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "Framework :: Zope :: 5",
        "License :: OSI Approved :: Zope Public License",
        "Operating System :: OS Independent",
        ],
      keywords='Firebird',
      author='Hajime Nakagami',
      author_email='nakagami@gmail.com',
      url='https://github.com/nakagami/Products.FirebirdDA',
      license='ZPL',
      packages=find_packages(exclude=['ez_setup']),
      namespace_packages=['Products'],
      include_package_data=True,
      zip_safe=False,
      python_requires='>=3.11',
      install_requires=[
          'firebirdsql',
          'Products.ZSQLMethods',
      ],
      extras_require={
          'firebird-driver': ['firebird-driver>=1.4.0'],
      },
      entry_points="""
      # -*- Entry points: -*-
      """,
      )
