*** note: this has been merged into zinnia. see https://github.com/Fantomas42/django-blog-zinnia/commit/bd5efc5f6323cd3f6591b8bc538c0187c13c6ded#diff-0 ***

A django management command to import a Blogger blog into Zinnia.

I modified the wp2zinnia management command that was included with Zinnia.

Requirements:

    gdata (http://code.google.com/p/gdata-python-client/)

Installation:

    $ cd my_app
    $ mkdir management
    $ touch management/__init__.py
    $ mkdir management/commands/
    $ touch management/commands/__init__.py
    $ cp /path/to/blogger2zinnia.py  management/commands/

Usage:

    $ python manage.py blogger2zinnia --help
