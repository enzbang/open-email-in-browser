#!/usr/bin/env python3
"""open-email-in-browser.

Read an email file and start a webserver to display the HTML content
and the attachments. This is mostly meant to be an helper for mutt.
"""

from jinja2 import Template
from email.header import decode_header, make_header
from slugify import slugify
import chardet
import cherrypy
import email
import mimetypes
import os
import re
import subprocess
import socket
import sys


def get_resource(kind):
    """Get HTML or CSS resource.

    :param kind: 'html' or 'css'
    :type kind: str
    """
    from pkg_resources import resource_string
    resource = resource_string(
            __name__, os.path.join(
                'data/open-email-in-browser.' + kind)).decode('utf-8')
    return resource


class EmailContent(object):
    """Open an email and parse it."""

    def __init__(self, filename):
        """Read an email.

        :param filename: path to the email or '-' to read the message from
            stdin
        :type filename: str
        """
        if filename == '-':
            self.msg = email.message_from_string(sys.stdin.read())
        else:
            with open(filename) as f:
                self.msg = email.message_from_file(f)
        self.parts = {}
        self.inline_parts = {}

        for part in self.msg.walk():
            if part.get_content_maintype() == 'multiplart':
                continue
            part_filename = part.get_filename()
            if part_filename:
                part_filename_prefix, ext = os.path.splitext(part_filename)
                part_filename = slugify(part_filename_prefix) + ext
            content_type = part.get_content_type()
            content = part.get_payload(decode=True)
            content_charset = part.get_content_charset()

            if content_type.startswith('text/'):
                # Try to guess encoding and convert everything to utf-8
                detected = chardet.detect(content)
                if detected['confidence'] > 0.6:
                    part_encoding = detected['encoding']
                else:
                    part_encoding = content_charset
                content = content.decode(part_encoding).encode('utf-8')

            if content_type == 'text/plain' and \
                    not part_filename:
                self.parts['txt'] = (content, content_type)
            elif content_type == 'text/html' and \
                    not part_filename:
                self.parts['html'] = (content, content_type)
            elif part_filename:
                self.parts[part_filename] = (content, content_type)

                # Check whether this is a inline part, e.g. as images sent
                # with Apple Mail
                if part.get('Content-Disposition').startswith('inline'):
                    content_id = part.get('Content-Id')
                    if content_id.startswith('<') and content_id.endswith('>'):
                        content_id = content_id[1:-1]
                    # Add a link to the part with have extracted
                    self.inline_parts[content_id] = part_filename

    @property
    def subject(self):
        """Return the email subject, properly decoded."""
        return str(make_header(decode_header(self.msg['Subject'])))

    @property
    def from_addr(self):
        """Return the email from addr, properly decoded."""
        return str(make_header(decode_header(self.msg['From'])))

    def get_attachment(self, name):
        """Get attachment content and content type.

        :param name: name of the attachemnt
        :type name: str
        :rtype: tuple[str][str]
        :return: the content and content_type
        """
        return self.parts.get(name, ('', ''))

    def get_main_content(self):
        """Get main content (HTML by default else plain text)."""
        content, content_type = self.get_attachment('html')
        if not content:
            content, content_type = self.get_attachment('txt')
        return cid_links(content), content_type

    def get_attachments_list(self):
        """Get the attachments list."""
        other_parts = [
                name for name in self.parts
                if name not in ('txt', 'html')]
        return other_parts


def cid_links(content):
    """Fix cid: links to open the extracted attachments."""
    return re.sub(b'src="cid:', b'src="/cid?name=', content)


class HTTPEmailViewer(object):
    """Our cherrypy app."""

    def __init__(self, email):
        """Initialize the viewer.

        :param email: the email to read (or '-' to read from stdin)
        :type email: str
        """
        self.email = email
        self.last_email = EmailContent(self.email)

    def get_attachment(self, name):
        if name in self.last_email.inline_parts:
            # If inline part then get the "real" attachment
            filename = self.last_email.inline_parts[name]
        elif name in self.last_email.parts:
            filename = name
        else:
            filename = name.rsplit('@', 1)[0]
        return self.last_email.get_attachment(filename)

    @cherrypy.expose
    def index(self, name='main'):
        """Return the main page.

        :param name: name of the attachment to display
        :type name: str
        """
        _, part_content_type = self.get_attachment(name)
        return Template(get_resource(kind='html')).render(
            subject=self.last_email.subject,
            from_addr=self.last_email.from_addr,
            partname=name,
            part_content_type=part_content_type,
            css=get_resource(kind='css'),
            attachments=self.last_email.get_attachments_list())

    @cherrypy.expose
    def cid(self, name):
        """Return a cid: attachment content."""
        assert self.last_email is not None

        if name in self.last_email.inline_parts:
            # If inline part then get the "real" attachment
            filename = self.last_email.inline_parts[name]
        else:
            filename = name.rsplit('@', 1)[0]
        return self.last_email.get_attachment(filename)

    @cherrypy.expose
    def view(self, name):
        """Return an attachment content to view inline."""
        assert self.last_email is not None
        filename = name.rsplit('@', 1)[0]
        if name == 'main':
            content, content_type = self.last_email.get_main_content()
        else:
            content, content_type = self.last_email.get_attachment(filename)
        if content_type == 'application/octet-stream':
            content_type, _ = mimetypes.guess_type(filename)
        cherrypy.response.headers['Content-Type'] = content_type
        if content_type == 'text/plain':
            cherrypy.response.headers['Content-Type'] = 'text/html'
            return b'<pre>' + content + b'</pre>'
        elif not content_type or (
                not content_type.startswith('text/') and
                not content_type.startswith('image/')):
            cherrypy.response.headers['Content-Type'] = 'text/html'
            return '<div class="lead">Cannot display inline</aiv>'
        return content

    @cherrypy.expose
    def download(self, name):
        """Download an attachment."""
        cherrypy.response.headers['Content-Disposition'] = \
            'attachment; filename="%s"' % name
        assert self.last_email is not None
        filename = name.rsplit('@', 1)[0]
        if name == 'main':
            content, content_type = self.last_email.get_main_content()
        else:
            content, content_type = self.last_email.get_attachment(filename)
        cherrypy.response.headers['Content-Type'] = content_type
        return content


def main():
    """Start the cherrypy server."""
    mimetypes.add_type('text/x-ada', '.ads')
    mimetypes.add_type('text/x-ada', '.adb')
    cherrypy.log.screen = False
    cherrypy.server.socket_port = 8080
    cherrypy.server.socket_host = socket.gethostbyaddr(socket.gethostname())[0]
    cherrypy.tree.mount(
        HTTPEmailViewer(sys.argv[1]), "/", {'/': {}})
    cherrypy.engine.start()
    try:
        open_cmd = 'xdg-open' if sys.platform.startswith('linux') else 'open'
        try:
            subprocess.check_call(
                [open_cmd,
                 'http://%s:%d' % (
                    cherrypy.server.socket_host,
                    cherrypy.server.socket_port)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)
        except subprocess.CalledProcessError:
            print('open http://%s:%d to see the email in your browser' % (
                cherrypy.server.socket_host,
                cherrypy.server.socket_port))
        sys.stdin.read(1)
        print('stopping the server, please wait...')
    finally:
        cherrypy.engine.exit()
        cherrypy.server.stop()
