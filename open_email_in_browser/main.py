#!/usr/bin/env python3

from email.header import decode_header, make_header
from slugify import slugify
import chardet
import cherrypy
import email
import mimetypes
import os
import re
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
<!-- Optional theme -->
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap-theme.min.css" integrity="sha384-rHyoN1iRsVXV4nD0JutlnGaslCJuC7uwjduW9SVrLvRYooPp2bWYgmgJQIXwl/Sp" crossorigin="anonymous">


  <style>{css}</style>

</head>

<body>
  <div class="container">
    <div class="page-header">
    <h1>{subject} <small>{from_addr}</small></h1>
    </div>
  {toc}
  <p><a href='/download?name={partname}'>Download attachment</a></p>
  <div id="root">
      <iframe sandbox seamless src='/view?name={partname}'></iframe>
  </div>

  </div>
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

        for part in self.msg.walk():
            if part.get_content_maintype() == 'multiplart':
                continue
            part_filename = part.get_filename()
            if part_filename:
                part_filename = slugify(part_filename)
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
        toc = '<ul class="nav nav-tabs">'
        for name in self.parts.keys():
            if name not in ('txt', 'html'):
                toc += '<li><a href="?name={name}">' \
                    '{name}</a></li>'.format(name=name)
        toc += '</ul>'
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
        elif not content_type or not content_type.startswith('text/'):
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
    cherrypy.tree.mount(
        HTTPEmailViewer(sys.argv[1]), "/", {'/': {}})
    cherrypy.engine.start()
    try:
        open_cmd = 'xdg-open' if sys.platform.startswith('linux') else 'open'
        os.system(open_cmd + ' http://localhost:8080')
        sys.stdin.read(1)
        print('stopping the server, please wait...')
    finally:
        cherrypy.engine.exit()
        cherrypy.server.stop()
