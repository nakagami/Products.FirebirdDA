from setuptools import setup, find_packages

version = '0.7.0'

setup(name='Products.FirebirdDA',
      version=version,
      description="Firebird database adapter for Zope4",
      long_description=open("README.rst").read(),
      # Get more strings from
      # http://pypi.python.org/pypi?:action=list_classifiers
      classifiers=[
        "Programming Language :: Python",
        "Framework :: Zope4",
        "License :: OSI Approved :: Zope Public License",
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
      install_requires=[
          'firebirdsql',
          'Products.ZSQLMethods',
      ],
      entry_points="""
      # -*- Entry points: -*-
      """,
      )
