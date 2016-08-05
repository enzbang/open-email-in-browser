from setuptools import setup, find_packages

setup(
    name='open-email-in-browser',
    version='0.0.1',
    description='Open an email in a web browser, view HTML content'
    ' and attachments',
    author='Olivier Ramonat',
    author_email='enzbang@ramonat.fr',

    license='MIT',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
    ],
    keywords='mutt email MUA',
    packages=find_packages(),
    install_requires=['cherrypy', 'chardet'],
    entry_points={
        'console_scripts': [
            'open-email-in-browser=open_email_in_browser.main:main',
        ],
    },
)
