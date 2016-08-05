# Open email in browser

This project provides a simple helper script to open a email in a web browser and to quickly view/download attachments.

This is mostly meant for console based client, e.g. for mutt, to view messages that embedded images in HTML.

To install run:

```bash
python setup.py install
```

To integrate with mutt, add:

```
macro index,pager P "<enter-command>unset wait_key<enter><pipe-message>cat > /tmp/mutt-email<enter><shell-escape>open-email-in-browser /tmp/mutt-email<enter>"
```
