"""Blogger to Zinnia command module"""

# based on wp2zinnia.py

import sys
from datetime import datetime
from optparse import make_option
from gdata import service as gdata_service

from django.utils.html import strip_tags
from django.db.utils import IntegrityError
from django.utils.encoding import smart_str
from django.utils.text import truncate_words
from django.contrib.sites.models import Site
from django.contrib.auth.models import User
from django.template.defaultfilters import slugify
from django.contrib.comments.models import Comment
from django.core.management.base import CommandError
from django.core.management.base import LabelCommand

from tagging.models import Tag
from django.contrib.contenttypes.models import ContentType


from zinnia import __version__
from zinnia.models import Entry
from zinnia.models import Category
from zinnia.managers import DRAFT, HIDDEN, PUBLISHED

from getpass import getpass
import gdata

class Command(LabelCommand):
    """Command object for importing a Blogger blog
    into Zinnia via Google's gdata API."""
    help = 'Import a Blogger blog into Zinnia.'

    args = ''

    option_list = LabelCommand.option_list + (
        make_option('--blogger-username', dest='blogger_username', default='',
                    help='The username to login to Blogger with'),
        make_option('--category-title', dest='category_title', default='',
                    help='The Zinnia category to import Blogger posts to'),
        make_option('--blogger-blog-id', dest='blogger_blog_id', default='',
                    help='The id of the Blogger blog to import'),
        make_option('--author', dest='author', default='',
                    help='All imported entries belong to specified author')
        )

    SITE = Site.objects.get_current()

    def __init__(self):
        """Init the Command and add custom styles"""
        super(Command, self).__init__()
        self.style.TITLE = self.style.SQL_FIELD
        self.style.STEP = self.style.SQL_COLTYPE
        self.style.ITEM = self.style.HTTP_INFO

    def write_out(self, message, verbosity_level=1):
        """Convenient method for outputing"""
        if self.verbosity and self.verbosity >= verbosity_level:
            sys.stdout.write(smart_str(message))
            sys.stdout.flush()

    def handle(self, **options):
        self.verbosity = int(options.get('verbosity', 1))
        self.blogger_username = options.get('blogger_username')
        self.category_title = options.get('category_title')
        self.blogger_blog_id = options.get('blogger_blog_id')

        if not self.blogger_username:
            self.blogger_username = raw_input('Blogger username: ')
            if not self.blogger_username:
                raise CommandError('Invalid Blogger username')

        self.blogger_password = getpass('Blogger password: ')
        try:
            self.blogger_manager = BloggerManager(self.blogger_username, self.blogger_password)
        except gdata_service.BadAuthentication:
            raise CommandError('Incorrect Blogger username or password')

        default_author = options.get('author')
        if default_author:
            try:
                self.default_author = User.objects.get(username=default_author)
            except User.DoesNotExist:
                raise CommandError('Invalid Zinnia username for default author "%s"' % default_author)
        else:
            self.default_author = User.objects.all()[0]

        if not self.blogger_blog_id:
            self.select_blog_id()

        if not self.category_title:
            self.category_title = raw_input('Category title for imported entries: ')
            if not self.category_title:
                raise CommandError('Invalid category title')

        self.write_out(self.style.TITLE('Starting migration from Blogger to Zinnia %s\n' % __version__))
        self.import_posts()
        self.write_out(self.style.TITLE('Finished importing Blogger to Zinnia\n'))


    def select_blog_id(self):
        blogs_list = [blog for blog in self.blogger_manager.get_blogs()]
        while True:
            i = 0
            blogs = {}
            self.write_out('\n')
            for blog in blogs_list:
                i += 1
                blogs[i] = blog
                self.write_out('\n  %s) %s (%s)' % (i, blog.title.text, get_blog_id(blog)))
            try:
                blog_index = int(raw_input('\n  Select a blog to import: '))
                blog = blogs[blog_index]
                break
            except (ValueError, KeyError):
                self.write_out(self.style.ERROR('Please enter a valid blog number\n'))

        self.blogger_blog_id = get_blog_id(blog)

    def get_category(self):
        category, created = Category.objects.get_or_create(
            title=self.category_title,
            slug=slugify(self.category_title)[:255])

        if created:
            category.save()

        return category

    def import_posts(self):
        category = self.get_category()

        for post in self.blogger_manager.get_posts(self.blogger_blog_id):
            creation_date = convert_blogger_timestamp(post.published.text)
            status = DRAFT if is_draft(post) else PUBLISHED
            title = post.title.text or ''
            content = post.content.text or ''
            slug = slugify(post.title.text or get_post_id(post))[:255]
            try:
                entry = Entry.objects.get(sites=self.SITE,
                                          authors=self.default_author,
                                          categories=category,
                                          status=status,
                                          title=title,
                                          content=content,
                                          creation_date=creation_date,
                                          slug=slug)
                output = self.style.TITLE('Skipped %s (already migrated)\n'
                    % entry)
                continue
            except Entry.DoesNotExist:
                entry = Entry(status=status, title=title, content=content,
                              creation_date=creation_date, slug=slug)
                if self.default_author:
                    entry.author = self.default_author
                entry.tags = ','.join([slugify(cat.term) for cat in post.category])
                entry.last_update = convert_blogger_timestamp(post.updated.text)
                entry.save()
                entry.sites.add(self.SITE)
                entry.categories.add(category)
                entry.authors.add(self.default_author)
                try:
                    self.import_comments(entry, post)
                except gdata_service.RequestError:
                    # comments not available for this post
                    pass
                output = self.style.TITLE('Migrated %s + %s comments\n'
                    % (entry, len(Comment.objects.for_model(entry))))

            self.write_out(output)

    def import_comments(self, entry, post):
        blog_id = self.blogger_blog_id
        post_id = get_post_id(post)
        comments = self.blogger_manager.get_comments(blog_id, post_id)
        entry_content_type = ContentType.objects.get_for_model(Entry)
        
        for comment in comments:
            submit_date = convert_blogger_timestamp(comment.published.text)
            content = comment.content.text

            author = comment.author[0]
            if author:
                user_name = author.name.text if author.name else ''
                user_email = author.email.text if author.email else ''
                user_url = author.uri.text if author.uri else ''

            else:
                user_name = ''
                user_email = ''
                user_url = ''

            com, created = Comment.objects.get_or_create(
                content_type=entry_content_type,
                object_pk=entry.pk,
                comment=content,
                submit_date=submit_date,
                site=self.SITE,
                user_name=user_name,
                user_email=user_email,
                user_url=user_url)

            if created:
                com.save()

# thanks to author of
# http://github.com/codeape2/python-blogger/tree/master/blogger.py
# for examples of the Blogger API

def convert_blogger_timestamp(timestamp):
    # parse 2010-12-19T15:37:00.003
    date_string = timestamp[:-6]
    return datetime.strptime(date_string, '%Y-%m-%dT%H:%M:%S.%f')

def is_draft(post):
    if post.control:
        if post.control.draft:
            if post.control.draft.text == 'yes':
                return True
    return False

def get_blog_id(blog):
    return blog.GetSelfLink().href.split('/')[-1]

def get_post_id(post):
    return post.GetSelfLink().href.split('/')[-1]


class BloggerManager(object):

    def __init__(self, username, password):
        self.service = gdata_service.GDataService(username, password)
        self.service.server = 'www.blogger.com'
        self.service.service = 'blogger'
        self.service.ProgrammaticLogin()

    def get_blogs(self):
        feed = self.service.Get('/feeds/default/blogs')
        for blog in feed.entry:
            yield blog

    def get_posts(self, blog_id):
        feed = self.service.Get('/feeds/%s/posts/default' % blog_id)
        for post in feed.entry:
            yield post

    def get_comments(self, blog_id, post_id):
        feed = self.service.Get('/feeds/%s/%s/comments/default' % (blog_id, post_id))
        for comment in feed.entry:
            yield comment
