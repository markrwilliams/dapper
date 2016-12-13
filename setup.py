from setuptools import setup, find_packages

setup(name="dapper",
      description="Asynchronous, declarative parsing",
      author="Mark Williams",
      author_email="mrw@enotuniq.org",
      install_requires=["attrs"],
      version="16.0.0",
      packages=find_packages())
