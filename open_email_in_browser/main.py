#!/usr/bin/env python3

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


CSS = """
@charset "utf-8";
html {
  /* Change default typefaces here */
  font-family: serif;
  font-size: 137.5%;
  -webkit-font-smoothing: antialiased;
}

body {
    margin: 0px;
    padding: 0px;
}

/* iframe's parent node */
div#root {
    position: fixed;
    width: 100%;
    height: 100%;
}

/* iframe itself */
div#root > iframe {
    display: block;
    width: 100%;
    height: 100%;
    border: none;
    padding-bottom: 10em;
}
"""


TEMPLATE = """
<!doctype html>

<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">


  <title>{subject}</title>
<!-- Latest compiled and minified CSS -->
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css" integrity="sha384-BVYiiSIFeK1dGmJRAkycuHAHRg32OmUcww7on3RYdg4Va+PmSTsz/K68vbdEjh4u" crossorigin="anonymous">
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootswatch/3.3.7/yeti/bootstrap.min.css">
  <style>{css}</style>
</head>

<body>
  <div class="container">
    <div class="page-header">
    <h1>{subject} <small>{from_addr}</small></h1>
    </div>
  {toc}
  <div id="root">
      <iframe sandbox seamless src='/view?name={partname}'></iframe>
  </div>

  </div>


  <script src="https://ajax.googleapis.com/ajax/libs/jquery/1.12.4/jquery.min.js"></script>
  <!-- Latest compiled and minified JavaScript -->
  <script src="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/js/bootstrap.min.js" integrity="sha384-Tc5IQib027qvyjSMfHjOMaLkfuWVxZxUPnCJA7l2mCWNIpG9mGCD8wGNIcPD7Txa" crossorigin="anonymous"></script>

</body>
</html>
"""


class EmailContent(object):

    def __init__(self, filename):
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
        return str(make_header(decode_header(self.msg['Subject'])))

    @property
    def from_addr(self):
        return str(make_header(decode_header(self.msg['From'])))

    def get_attachment(self, name):
        return self.parts.get(name, ('', ''))

    def get_main_content(self):
        content, content_type = self.get_attachment('html')
        if not content:
            content, content_type = self.get_attachment('txt')
        return cid_links(content), content_type

    def get_toc(self):

        other_parts = [name for name in self.parts if name not in ('txt', 'html')]

        if not other_parts:
            return ''
        toc = '<ul class="nav nav-tabs">'
        for name in other_parts:
            toc += '<li><a href="?name={name}">' \
                '{name}</a></li>'.format(name=name)
        toc += '<li><a class="dropdown-toggle" data-toggle="dropdown"' \
                ' href="#" role="button" aria-haspopup="true"' \
                ' aria-expanded="false">' \
                '<span class="glyphicon glyphicon-download"></span>' \
                '<span class="caret"></span></a>' \
                '<ul class="dropdown-menu">'
        for name in other_parts:
            toc += '<li><a href="/download?name={name}">{name}</li>'.format(
                    name=name)
        toc += '</ul></li></ul>'
        return toc


def cid_links(content):
    return re.sub(b'src="cid:', b'src="/cid?name=', content)


class HTTPEmailViewer(object):

    def __init__(self, email):
        self.email = email
        self.last_email = EmailContent(self.email)

    @cherrypy.expose
    def index(self, name='main'):
        return TEMPLATE.format(
            subject=self.last_email.subject,
            from_addr=self.last_email.from_addr,
            partname=name,
            css=CSS,
            toc=self.last_email.get_toc())

    @cherrypy.expose
    def cid(self, name):
        assert self.last_email is not None

        if name in self.last_email.inline_parts:
            # If inline part then get the "real" attachment
            filename = self.last_email.inline_parts[name]
        else:
            filename = name.rsplit('@', 1)[0]
        return self.last_email.get_attachment(filename)

    @cherrypy.expose
    def view(self, name):
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
